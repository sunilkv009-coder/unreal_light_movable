using UnrealBuildTool;

public class CameraMatch : ModuleRules
{
	public CameraMatch(ReadOnlyTargetRules Target) : base(Target)
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
			"EditorSubsystem",
			"LevelEditor",
			"AssetTools",
			"ContentBrowser",
			"AssetRegistry",
			"MaterialEditor",
			"CinematicCamera",
			"DesktopPlatform",
		});
	}
}
