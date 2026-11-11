using UnrealBuildTool;

public class Anansi : ModuleRules
{
    public Anansi(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine", "HTTP", "Json" });
    }
}
