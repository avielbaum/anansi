#include "AnansiClient.h"

#include "Containers/Ticker.h"
#include "Dom/JsonObject.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
using FObj = TSharedPtr<FJsonObject>;

FString ToJson(const FObj& O)
{
	FString S;
	TSharedRef<TJsonWriter<>> W = TJsonWriterFactory<>::Create(&S);
	FJsonSerializer::Serialize(O.ToSharedRef(), W);
	return S;
}

FObj FromJson(const FString& S)
{
	FObj O;
	TSharedRef<TJsonReader<>> R = TJsonReaderFactory<>::Create(S);
	if (!FJsonSerializer::Deserialize(R, O)) O.Reset();
	return O;
}

FString Str(const FObj& O, const TCHAR* K)
{
	FString V;
	if (O.IsValid()) O->TryGetStringField(K, V);
	return V;
}

TArray<TSharedPtr<FJsonValue>> EntitiesJson(const TArray<FAnansiEntity>& Es)
{
	TArray<TSharedPtr<FJsonValue>> Out;
	for (const FAnansiEntity& E : Es)
	{
		FObj O = MakeShared<FJsonObject>();
		O->SetStringField(TEXT("id"), E.Id);
		O->SetStringField(TEXT("name"), E.Name);
		if (!E.Role.IsEmpty()) O->SetStringField(TEXT("role"), E.Role);
		Out.Add(MakeShared<FJsonValueObject>(O));
	}
	return Out;
}

FObj WorldJson(const FAnansiWorld& W)
{
	FObj O = MakeShared<FJsonObject>();
	O->SetArrayField(TEXT("npcs"), EntitiesJson(W.Npcs));
	O->SetArrayField(TEXT("locations"), EntitiesJson(W.Locations));
	O->SetArrayField(TEXT("items"), EntitiesJson(W.Items));
	return O;
}

FObj GenBody(const FAnansiWorld& W, int32 Count, const FString& Theme, const FString& Difficulty,
             const FString& Story, const FString& Player)
{
	FObj B = MakeShared<FJsonObject>();
	B->SetObjectField(TEXT("world"), WorldJson(W));
	B->SetNumberField(TEXT("steps"), Count);
	B->SetStringField(TEXT("theme"), Theme);
	B->SetStringField(TEXT("difficulty"), Difficulty.IsEmpty() ? TEXT("normal") : Difficulty);
	B->SetStringField(TEXT("story_so_far"), Story);
	B->SetStringField(TEXT("player"), Player);
	return B;
}

// Streaming state shared between the progress callback, the completion callback and the first-sentence timer.
struct FStreamState
{
	FString Said;
	int32 Consumed = 0;
	bool bGot = false;
	bool bStop = false;
	bool bFinished = false;
	FTSTicker::FDelegateHandle Timer;
	FAnansiSentenceDelegate OnSentence;
	FAnansiReplyDelegate OnDone;
};

// Reads the complete "data: {...}" lines in the body so far that have not been read yet and hands each sentence on.
void Pump(const TSharedRef<FStreamState>& S, const FString& Body)
{
	int32 Start = S->Consumed;
	while (!S->bStop)
	{
		const int32 End = Body.Find(TEXT("\n"), ESearchCase::CaseSensitive, ESearchDir::FromStart, Start);
		if (End == INDEX_NONE) break;
		const FString Line = Body.Mid(Start, End - Start).TrimEnd();
		Start = End + 1;
		if (!Line.StartsWith(TEXT("data: {"))) continue;
		if (Line.StartsWith(TEXT("data: {\"error\""))) { S->bStop = true; break; } // the gateway could not serve the stream
		const FObj J = FromJson(Line.Mid(6));
		const TArray<TSharedPtr<FJsonValue>>* Choices = nullptr;
		if (!J.IsValid() || !J->TryGetArrayField(TEXT("choices"), Choices) || Choices->Num() == 0) continue;
		const TSharedPtr<FJsonObject>* Choice = nullptr;
		const TSharedPtr<FJsonObject>* Delta = nullptr;
		FString Text;
		if ((*Choices)[0]->TryGetObject(Choice) && (*Choice)->TryGetObjectField(TEXT("delta"), Delta)
			&& (*Delta)->TryGetStringField(TEXT("content"), Text) && !Text.IsEmpty())
		{
			S->Said += Text;
			S->bGot = true;
			S->OnSentence.ExecuteIfBound(Text);
		}
	}
	S->Consumed = Start;
}
} // namespace

UAnansiClient* UAnansiClient::Create(UObject* Outer, const FString& InBaseUrl, const FString& InTitleId, const FString& InTitleKey)
{
	UAnansiClient* C = NewObject<UAnansiClient>(Outer);
	C->BaseUrl = InBaseUrl.TrimEnd();
	while (C->BaseUrl.EndsWith(TEXT("/"))) C->BaseUrl.LeftChopInline(1);
	C->TitleId = InTitleId;
	C->TitleKey = InTitleKey;
	return C;
}

TSharedRef<IHttpRequest, ESPMode::ThreadSafe> UAnansiClient::MakeRequest(const FString& Path, const FString& Body, float Timeout) const
{
	TSharedRef<IHttpRequest, ESPMode::ThreadSafe> R = FHttpModule::Get().CreateRequest();
	R->SetURL(BaseUrl + Path);
	R->SetVerb(TEXT("POST"));
	R->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
	R->SetHeader(TEXT("X-Anansi-Title"), TitleId);
	R->SetHeader(TEXT("X-Anansi-Key"), TitleKey);
	R->SetHeader(TEXT("X-Player-Token"), PlayerToken);
	R->SetContentAsString(Body);
	R->SetTimeout(Timeout);
	return R;
}

FAnansiReply UAnansiClient::Fallback() const
{
	FAnansiReply R;
	R.Say = FallbackLine;
	R.Action = TEXT("none");
	R.Source = TEXT("fallback");
	return R;
}

void UAnansiClient::Chat(const TArray<FAnansiMessage>& Messages, const FString& NpcId, bool bStructured, FAnansiReplyDelegate OnReply)
{
	FObj B = MakeShared<FJsonObject>();
	if (!NpcId.IsEmpty()) B->SetStringField(TEXT("npc_id"), NpcId);
	B->SetBoolField(TEXT("structured"), bStructured);
	TArray<TSharedPtr<FJsonValue>> Msgs;
	for (const FAnansiMessage& M : Messages)
	{
		FObj O = MakeShared<FJsonObject>();
		O->SetStringField(TEXT("role"), M.Role);
		O->SetStringField(TEXT("content"), M.Content);
		Msgs.Add(MakeShared<FJsonValueObject>(O));
	}
	B->SetArrayField(TEXT("messages"), Msgs);

	auto Req = MakeRequest(TEXT("/v1/npc"), ToJson(B), TimeoutSeconds);
	Req->OnProcessRequestComplete().BindWeakLambda(this, [this, OnReply](FHttpRequestPtr, FHttpResponsePtr Resp, bool bOk)
	{
		if (bOk && Resp.IsValid() && Resp->GetResponseCode() == 200)
		{
			const FObj J = FromJson(Resp->GetContentAsString());
			FAnansiReply R;
			R.Say = Str(J, TEXT("say"));
			if (!R.Say.IsEmpty()) // an empty reply is as good as none
			{
				R.Action = Str(J, TEXT("action"));
				if (R.Action.IsEmpty()) R.Action = TEXT("none");
				J->TryGetBoolField(TEXT("filtered"), R.bFiltered);
				R.Source = TEXT("gateway");
				OnReply.ExecuteIfBound(R);
				return;
			}
		}
		OnReply.ExecuteIfBound(Fallback());
	});
	Req->ProcessRequest();
}

void UAnansiClient::ChatStream(const TArray<FAnansiMessage>& Messages, const FString& NpcId, FAnansiSentenceDelegate OnSentence, FAnansiReplyDelegate OnDone)
{
	FObj B = MakeShared<FJsonObject>();
	B->SetBoolField(TEXT("stream"), true);
	FObj Meta = MakeShared<FJsonObject>();
	Meta->SetStringField(TEXT("npc_id"), NpcId);
	B->SetObjectField(TEXT("anansi"), Meta);
	TArray<TSharedPtr<FJsonValue>> Msgs;
	for (const FAnansiMessage& M : Messages)
	{
		FObj O = MakeShared<FJsonObject>();
		O->SetStringField(TEXT("role"), M.Role);
		O->SetStringField(TEXT("content"), M.Content);
		Msgs.Add(MakeShared<FJsonValueObject>(O));
	}
	B->SetArrayField(TEXT("messages"), Msgs);

	TSharedRef<FStreamState> S = MakeShared<FStreamState>();
	S->OnSentence = OnSentence;
	S->OnDone = OnDone;
	auto Req = MakeRequest(TEXT("/v1/chat/completions"), ToJson(B), StreamTimeoutSeconds);

	// Ends the stream once: what was said stands; if nothing arrived, the fallback line is the answer.
	TWeakObjectPtr<UAnansiClient> Self(this);
	auto Finish = [Self, S]()
	{
		if (S->bFinished) return;
		S->bFinished = true;
		FTSTicker::GetCoreTicker().RemoveTicker(S->Timer);
		FAnansiReply R;
		if (S->bGot)
		{
			R.Say = S->Said;
			R.Source = TEXT("gateway");
		}
		else
		{
			R = Self.IsValid() ? Self->Fallback() : FAnansiReply();
			S->OnSentence.ExecuteIfBound(R.Say);
		}
		S->OnDone.ExecuteIfBound(R);
	};

	// shortcut: needs the HTTP backend to report body data while the response is still open. Where it only reports
	// at the end, all sentences arrive together when the reply is complete (still correct, just not progressive).
	Req->OnRequestProgress().BindWeakLambda(this, [S](FHttpRequestPtr R, int32, int32)
	{
		if (R.IsValid() && R->GetResponse().IsValid()) Pump(S, R->GetResponse()->GetContentAsString());
	});
	Req->OnProcessRequestComplete().BindWeakLambda(this, [S, Finish](FHttpRequestPtr, FHttpResponsePtr Resp, bool bOk)
	{
		if (bOk && Resp.IsValid() && Resp->GetResponseCode() == 200) Pump(S, Resp->GetContentAsString());
		Finish();
	});
	// No sentence within TimeoutSeconds: give up on the gateway and answer from the fallback.
	S->Timer = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateWeakLambda(this, [S, Finish, Req](float)
	{
		if (!S->bGot && !S->bFinished) { Finish(); Req->CancelRequest(); }
		return false;
	}), TimeoutSeconds);
	Req->ProcessRequest();
}

void UAnansiClient::RequestQuest(const FAnansiWorld& World, int32 Steps, const FString& Theme, const FString& Difficulty,
                                 const FString& StorySoFar, const FString& Player, FAnansiQuestDelegate OnResult)
{
	auto Req = MakeRequest(TEXT("/v1/quest"), ToJson(GenBody(World, Steps, Theme, Difficulty, StorySoFar, Player)), GenerationTimeoutSeconds);
	Req->OnProcessRequestComplete().BindWeakLambda(this, [OnResult](FHttpRequestPtr, FHttpResponsePtr Resp, bool bOk)
	{
		FAnansiQuestResult Out;
		Out.Source = TEXT("fallback");
		const TSharedPtr<FJsonObject>* Q = nullptr;
		FObj J;
		if (bOk && Resp.IsValid() && Resp->GetResponseCode() == 200) J = FromJson(Resp->GetContentAsString());
		if (J.IsValid() && J->TryGetObjectField(TEXT("quest"), Q))
		{
			Out.Source = TEXT("gateway");
			Out.bHasQuest = true;
			Out.Quest.Title = Str(*Q, TEXT("title"));
			Out.Quest.Summary = Str(*Q, TEXT("summary"));
			Out.Quest.RewardTier = Str(*Q, TEXT("reward_tier"));
			Out.Quest.StorySummary = Str(*Q, TEXT("story_summary"));
			const TArray<TSharedPtr<FJsonValue>>* Steps = nullptr;
			if ((*Q)->TryGetArrayField(TEXT("steps"), Steps))
				for (const TSharedPtr<FJsonValue>& V : *Steps)
				{
					const TSharedPtr<FJsonObject>* O = nullptr;
					if (!V->TryGetObject(O)) continue;
					FAnansiQuestStep St;
					St.Objective = Str(*O, TEXT("objective"));
					St.TargetId = Str(*O, TEXT("target_id"));
					St.Description = Str(*O, TEXT("description"));
					Out.Quest.Steps.Add(St);
				}
		}
		OnResult.ExecuteIfBound(Out);
	});
	Req->ProcessRequest();
}

void UAnansiClient::RequestStoryline(const FAnansiWorld& World, int32 Beats, const FString& Theme, FAnansiStorylineDelegate OnResult)
{
	auto Req = MakeRequest(TEXT("/v1/storyline"), ToJson(GenBody(World, Beats, Theme, TEXT("normal"), TEXT(""), TEXT(""))), GenerationTimeoutSeconds);
	Req->OnProcessRequestComplete().BindWeakLambda(this, [OnResult](FHttpRequestPtr, FHttpResponsePtr Resp, bool bOk)
	{
		FAnansiStorylineResult Out;
		Out.Source = TEXT("fallback");
		const TSharedPtr<FJsonObject>* A = nullptr;
		FObj J;
		if (bOk && Resp.IsValid() && Resp->GetResponseCode() == 200) J = FromJson(Resp->GetContentAsString());
		if (J.IsValid() && J->TryGetObjectField(TEXT("storyline"), A))
		{
			Out.Source = TEXT("gateway");
			Out.bHasStoryline = true;
			Out.Logline = Str(*A, TEXT("logline"));
			const TArray<TSharedPtr<FJsonValue>>* Bs = nullptr;
			if ((*A)->TryGetArrayField(TEXT("beats"), Bs))
				for (const TSharedPtr<FJsonValue>& V : *Bs)
				{
					const TSharedPtr<FJsonObject>* O = nullptr;
					if (!V->TryGetObject(O)) continue;
					FAnansiBeat Beat;
					Beat.Title = Str(*O, TEXT("title"));
					Beat.Summary = Str(*O, TEXT("summary"));
					Beat.NpcId = Str(*O, TEXT("npc_id"));
					Beat.LocationId = Str(*O, TEXT("location_id"));
					Out.Beats.Add(Beat);
				}
		}
		OnResult.ExecuteIfBound(Out);
	});
	Req->ProcessRequest();
}
