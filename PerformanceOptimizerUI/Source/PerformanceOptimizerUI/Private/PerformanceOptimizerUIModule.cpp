#include "CoreMinimal.h"
#include "Framework/Application/SlateApplication.h"
#include "Framework/Docking/TabManager.h"
#include "Modules/ModuleManager.h"
#include "ToolMenus.h"
#include "Widgets/Docking/SDockTab.h"

#include "SPerformanceOptimizerTab.h"

#define LOCTEXT_NAMESPACE "PerformanceOptimizerUI"

static const FName PerformanceTabName(TEXT("PerformanceImprovements"));

class FPerformanceOptimizerUIModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		FGlobalTabmanager::Get()->RegisterNomadTabSpawner(
			PerformanceTabName,
			FOnSpawnTab::CreateRaw(this, &FPerformanceOptimizerUIModule::SpawnTab))
			.SetDisplayName(LOCTEXT("TabTitle", "Performance Improvements"))
			.SetTooltipText(LOCTEXT("TabTooltip", "Scan, toggle and auto-apply performance settings."))
			.SetMenuType(ETabSpawnerMenuType::Hidden);

		UToolMenus::RegisterStartupCallback(
			FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FPerformanceOptimizerUIModule::RegisterMenus));
	}

	virtual void ShutdownModule() override
	{
		UToolMenus::UnRegisterStartupCallback(this);
		UToolMenus::UnregisterOwner(this);
		if (FSlateApplication::IsInitialized())
		{
			FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(PerformanceTabName);
		}
	}

private:
	TSharedRef<SDockTab> SpawnTab(const FSpawnTabArgs& Args)
	{
		return SNew(SDockTab)
			.TabRole(ETabRole::NomadTab)
			[
				SNew(SPerformanceOptimizerTab)
			];
	}

	void RegisterMenus()
	{
		FToolMenuOwnerScoped OwnerScoped(this);
		UToolMenu* Menu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Tools");
		FToolMenuSection& Section = Menu->FindOrAddSection("PerformanceOptimizer");
		Section.AddMenuEntry(
			"OpenPerformanceImprovements",
			LOCTEXT("OpenTab", "Performance Improvements..."),
			LOCTEXT("OpenTabTooltip", "Open the Performance Improvements tab."),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateLambda([]()
			{
				FGlobalTabmanager::Get()->TryInvokeTab(PerformanceTabName);
			})));
	}
};

IMPLEMENT_MODULE(FPerformanceOptimizerUIModule, PerformanceOptimizerUI)

#undef LOCTEXT_NAMESPACE
