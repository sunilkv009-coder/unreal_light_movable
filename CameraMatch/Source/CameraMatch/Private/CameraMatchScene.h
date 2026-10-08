#pragma once

#include "CoreMinimal.h"

#include "CameraMatchSolver.h"

class ACineCameraActor;
class UTexture2D;

/**
 * Everything that changes the level or creates assets.
 *
 * Assets go to /Game/CameraMatch and are left unsaved (Save All keeps them; in Perforce
 * Unreal marks them for add when they are saved). Nothing is ever submitted.
 */
namespace CameraMatchScene
{
	struct FBackplateOptions
	{
		/** 0 = photo hidden, 1 = only the photo. */
		float Opacity = 0.5f;
		/** Show the photo only where nothing is rendered (sky / empty space), so 3D objects sit in front of it. */
		bool bBehindScene = false;
	};

	/** Imports a photo into /Game/CameraMatch/Backplates as a new texture asset. */
	UTexture2D* ImportBackplateTexture(const FString& File, FText& OutError);

	/** Checks a texture can be used as a backplate. */
	bool CanUseAsBackplate(const UTexture2D* Texture, FText& OutError);

	/** Spawns a Cine Camera matching the solve. Call inside a transaction. */
	ACineCameraActor* CreateCamera(const CameraMatch::FResult& Result, const FString& Label, FText& OutError);

	/** Sets the camera's transform, filmback and focal length. The caller calls Modify() (or not, for transient previews). */
	void ApplyCamera(ACineCameraActor* Camera, const CameraMatch::FResult& Result);

	/** Adds (or updates) the backplate post-process material on the camera. Call inside a transaction. */
	bool SetBackplate(ACineCameraActor* Camera, UTexture2D* Texture, const FBackplateOptions& Options, FText& OutError);

	/** Updates opacity and "behind scene" on the camera's existing backplate. False if it has none. */
	bool SetBackplateOptions(ACineCameraActor* Camera, const FBackplateOptions& Options);

	/** Removes the backplate material from the camera (the asset stays). Call inside a transaction. */
	void RemoveBackplate(ACineCameraActor* Camera);

	/** Remembers the handles and settings on the camera, so "Edit Selected Camera" can reopen them. */
	void WriteState(ACineCameraActor* Camera, const CameraMatch::FInput& Input, const FString& TexturePath, const FString& SourceFile,
		const FBackplateOptions& Options);
	bool ReadState(const ACineCameraActor* Camera, CameraMatch::FInput& OutInput, FString& OutTexturePath, FString& OutSourceFile,
		FBackplateOptions& OutOptions);

	/** Looks through the camera in the active level viewport. */
	void Pilot(ACineCameraActor* Camera);
}
