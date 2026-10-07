using UnrealBuildTool;

public class PerformanceOptimizerUI : ModuleRules
{
	public PerformanceOptimizerUI(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"Slate",
			"SlateCore",
			"ToolMenus",
			"UnrealEd",
			"Json",
			"PythonScriptPlugin",
		});
	}
}
