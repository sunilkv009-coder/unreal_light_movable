#include "CoreMinimal.h"
#include "Framework/Application/SlateApplication.h"
#include "Framework/Docking/TabManager.h"
#include "Modules/ModuleManager.h"
#include "Styling/AppStyle.h"
#include "ToolMenus.h"
#include "Widgets/Docking/SDockTab.h"

#include "SCameraMatchTab.h"

#define LOCTEXT_NAMESPACE "CameraMatch"

static const FName CameraMatchTabName(TEXT("CameraMatch"));

class FCameraMatchModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		FGlobalTabmanager::Get()->RegisterNomadTabSpawner(
			CameraMatchTabName,
			FOnSpawnTab::CreateRaw(this, &FCameraMatchModule::SpawnTab))
			.SetDisplayName(LOCTEXT("TabTitle", "Camera Match"))
			.SetTooltipText(LOCTEXT("TabTooltip", "Match a camera to a photo from its vanishing points, and use the photo as a backplate."))
			.SetIcon(FSlateIcon(FAppStyle::GetAppStyleSetName(), "ClassIcon.CineCameraActor"))
			.SetMenuType(ETabSpawnerMenuType::Hidden);

		UToolMenus::RegisterStartupCallback(
			FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FCameraMatchModule::RegisterMenus));
	}

	virtual void ShutdownModule() override
	{
		UToolMenus::UnRegisterStartupCallback(this);
		UToolMenus::UnregisterOwner(this);
		if (FSlateApplication::IsInitialized())
		{
			FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(CameraMatchTabName);
		}
	}

private:
	TSharedRef<SDockTab> SpawnTab(const FSpawnTabArgs& Args)
	{
		return SNew(SDockTab)
			.TabRole(ETabRole::NomadTab)
			[
				SNew(SCameraMatchTab)
			];
	}

	void RegisterMenus()
	{
		FToolMenuOwnerScoped OwnerScoped(this);
		UToolMenu* Menu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Tools");
		FToolMenuSection& Section = Menu->FindOrAddSection("CameraMatch");
		Section.AddMenuEntry(
			"OpenCameraMatch",
			LOCTEXT("OpenTab", "Camera Match (from Photo)..."),
			LOCTEXT("OpenTabTooltip", "Open the Camera Match tab: create a camera that matches a backplate photo."),
			FSlateIcon(FAppStyle::GetAppStyleSetName(), "ClassIcon.CineCameraActor"),
			FUIAction(FExecuteAction::CreateLambda([]()
			{
				FGlobalTabmanager::Get()->TryInvokeTab(CameraMatchTabName);
			})));
	}
};

IMPLEMENT_MODULE(FCameraMatchModule, CameraMatch)

#undef LOCTEXT_NAMESPACE
