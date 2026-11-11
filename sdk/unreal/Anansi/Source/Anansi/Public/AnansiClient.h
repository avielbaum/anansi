// Anansi game SDK for Unreal Engine 5 (written for 5.1 to 5.3; later versions compile with a deprecation warning).
// Same contract as sdk/anansi_client.py and sdk/unity/Anansi.cs: ask the gateway, and on timeout, 429 or any failure
// answer with FallbackLine so the game never stalls. Every result carries Source = "gateway" or "fallback".
// shortcut: UNTESTED. It has never been compiled or run in Unreal (no engine install was available when it was written).
#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "AnansiClient.generated.h"

USTRUCT(BlueprintType)
struct FAnansiMessage
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Anansi") FString Role = TEXT("user"); // system, user or assistant
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Anansi") FString Content;
};

USTRUCT(BlueprintType)
struct FAnansiReply
{
	GENERATED_BODY()
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Say;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Action = TEXT("none"); // one of the title's whitelisted actions, or "none"
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") bool bFiltered = false;       // the gateway replaced unsafe text
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Source;               // "gateway" or "fallback"
};

// The world your game already has. Quests and storylines can only use these ids.
USTRUCT(BlueprintType)
struct FAnansiEntity
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Anansi") FString Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Anansi") FString Name;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Anansi") FString Role; // optional, e.g. "blacksmith"
};

USTRUCT(BlueprintType)
struct FAnansiWorld
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Anansi") TArray<FAnansiEntity> Npcs;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Anansi") TArray<FAnansiEntity> Locations;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Anansi") TArray<FAnansiEntity> Items;
};

USTRUCT(BlueprintType)
struct FAnansiQuestStep
{
	GENERATED_BODY()
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Objective;  // talk_to, explore or fetch
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString TargetId;   // an id from the world you sent
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Description;
};

USTRUCT(BlueprintType)
struct FAnansiQuest
{
	GENERATED_BODY()
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Title;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Summary;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") TArray<FAnansiQuestStep> Steps;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString RewardTier;   // small, medium or large: map it to your own loot
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString StorySummary; // pass back as StorySoFar to continue a story
};

USTRUCT(BlueprintType)
struct FAnansiQuestResult
{
	GENERATED_BODY()
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Source;   // "gateway" or "fallback"
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") bool bHasQuest = false; // false on fallback: use your own authored quest
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FAnansiQuest Quest;
};

USTRUCT(BlueprintType)
struct FAnansiBeat
{
	GENERATED_BODY()
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Title;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Summary;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString NpcId;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString LocationId;
};

USTRUCT(BlueprintType)
struct FAnansiStorylineResult
{
	GENERATED_BODY()
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Source;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") bool bHasStoryline = false;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") FString Logline;
	UPROPERTY(BlueprintReadOnly, Category = "Anansi") TArray<FAnansiBeat> Beats;
};

DECLARE_DYNAMIC_DELEGATE_OneParam(FAnansiReplyDelegate, const FAnansiReply&, Reply);
DECLARE_DYNAMIC_DELEGATE_OneParam(FAnansiSentenceDelegate, const FString&, Sentence);
DECLARE_DYNAMIC_DELEGATE_OneParam(FAnansiQuestDelegate, const FAnansiQuestResult&, Result);
DECLARE_DYNAMIC_DELEGATE_OneParam(FAnansiStorylineDelegate, const FAnansiStorylineResult&, Result);

UCLASS(BlueprintType)
class ANANSI_API UAnansiClient : public UObject
{
	GENERATED_BODY()

public:
	/** Create one per game: UAnansiClient::Create(this, "https://gateway.example", "demo", "change-me"). */
	UFUNCTION(BlueprintCallable, Category = "Anansi", meta = (WorldContext = "Outer"))
	static UAnansiClient* Create(UObject* Outer, const FString& BaseUrl, const FString& TitleId, const FString& TitleKey);

	/** Proof of who the player is, from your platform (on Steam, the hex web-API auth ticket). Tokens expire: set a fresh one before each call if yours does. */
	UPROPERTY(BlueprintReadWrite, Category = "Anansi") FString PlayerToken;
	/** Shown (as Source "fallback") when the gateway fails, is slow or says no. Replace it with something in character. */
	UPROPERTY(BlueprintReadWrite, Category = "Anansi") FString FallbackLine = TEXT("...");
	/** Seconds to wait for a plain reply, or for the first sentence of a streamed one. */
	UPROPERTY(BlueprintReadWrite, Category = "Anansi") float TimeoutSeconds = 3.f;
	/** Seconds allowed for a whole streamed reply once it has started. */
	UPROPERTY(BlueprintReadWrite, Category = "Anansi") float StreamTimeoutSeconds = 30.f;
	/** Quest and storyline generation is slow (tens of seconds on a small GPU): use it on loading screens, not mid-conversation. */
	UPROPERTY(BlueprintReadWrite, Category = "Anansi") float GenerationTimeoutSeconds = 60.f;

	/** One reply. With bStructured the reply carries an Action from the title's whitelist. */
	UFUNCTION(BlueprintCallable, Category = "Anansi")
	void Chat(const TArray<FAnansiMessage>& Messages, const FString& NpcId, bool bStructured, FAnansiReplyDelegate OnReply);

	/** A reply one finished sentence at a time. OnSentence runs per sentence; OnDone runs once with the whole text.
	 *  If the gateway fails before the first sentence, OnSentence gets FallbackLine once. After text was shown, that text stands. */
	UFUNCTION(BlueprintCallable, Category = "Anansi")
	void ChatStream(const TArray<FAnansiMessage>& Messages, const FString& NpcId, FAnansiSentenceDelegate OnSentence, FAnansiReplyDelegate OnDone);

	/** One quest that can only use the characters, places and items in World. */
	UFUNCTION(BlueprintCallable, Category = "Anansi")
	void RequestQuest(const FAnansiWorld& World, int32 Steps, const FString& Theme, const FString& Difficulty,
	                  const FString& StorySoFar, const FString& Player, FAnansiQuestDelegate OnResult);

	UFUNCTION(BlueprintCallable, Category = "Anansi")
	void RequestStoryline(const FAnansiWorld& World, int32 Beats, const FString& Theme, FAnansiStorylineDelegate OnResult);

private:
	FString BaseUrl, TitleId, TitleKey;
	TSharedRef<class IHttpRequest, ESPMode::ThreadSafe> MakeRequest(const FString& Path, const FString& Body, float Timeout) const;
	FAnansiReply Fallback() const;
};
