#pragma once

#include "CoreMinimal.h"
#include "Input/Reply.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"

class FJsonObject;
class SVerticalBox;

/**
 * The "Performance Improvements" tab.
 *
 * Thin UI only: every action calls a function in perf_optimizer.py (Light
 * Mobility Tool plugin), which writes Saved/PerformanceOptimizer/ui_state.json.
 * The tab reads that file and draws one row per item: name, details, visual
 * impact, a toggle and the scan suggestion.
 */
class SPerformanceOptimizerTab : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SPerformanceOptimizerTab) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

private:
	/** Runs `perf_optimizer.<Call>` and reloads the state. */
	void RunPython(const FString& Call);
	void LoadState();
	void RequestRebuild();
	void RebuildItems();
	TSharedRef<SWidget> MakeItemRow(const TSharedPtr<FJsonObject>& Item);

	EActiveTimerReturnType OnRebuildTimer(double InCurrentTime, float InDeltaTime);
	EActiveTimerReturnType OnPollTimer(double InCurrentTime, float InDeltaTime);

	bool IsBusy() const;
	bool IsIdle() const { return !IsBusy(); }
	bool IsViewportRealtime() const;

	FText GetHeaderText() const;
	FText GetStatusText() const;
	FText GetResultsText() const;
	EVisibility GetResultsVisibility() const;

	FReply OnScanClicked();
	FReply OnAutoClicked();
	FReply OnMeasureClicked();
	FReply OnCancelClicked();
	FReply OnSaveClicked();
	FReply OnRevertClicked();
	FReply OnReportClicked();

	TSharedPtr<SVerticalBox> ItemsBox;
	TSharedPtr<FJsonObject> State;
	FString LastError;
	bool bIncludeLowImpact = false;
	bool bRebuildPending = false;
	bool bPolling = false;
};
