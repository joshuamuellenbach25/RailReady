package expo.modules.railreadyvolumekeys

import android.view.KeyEvent
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

// Volume keys are consumed ONLY while attached (camera screen focused). Otherwise MainActivity passes them through,
// so volume behaves normally everywhere else (REQ-1314).
object VolumeKeyBridge {
  @Volatile var attached = false
  var emit: ((String, Int) -> Unit)? = null

  /** Called from MainActivity.dispatchKeyEvent (injected by the config plugin). Returns true if consumed. */
  @JvmStatic
  fun handle(event: KeyEvent): Boolean {
    if (!attached) return false
    val dir = when (event.keyCode) {
      KeyEvent.KEYCODE_VOLUME_UP -> "up"
      KeyEvent.KEYCODE_VOLUME_DOWN -> "down"
      else -> return false
    }
    if (event.action == KeyEvent.ACTION_DOWN) emit?.invoke(dir, event.repeatCount)
    return true // consume both DOWN and UP so the system volume does not change while capturing
  }
}

class RailReadyVolumeKeysModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("RailReadyVolumeKeys")
    Events("onVolumeKey")
    OnCreate { VolumeKeyBridge.emit = { d, r -> sendEvent("onVolumeKey", mapOf("direction" to d, "repeat" to r)) } }
    Function("attach") { VolumeKeyBridge.attached = true }
    Function("detach") { VolumeKeyBridge.attached = false }
    OnActivityEntersBackground { VolumeKeyBridge.attached = false }
    OnDestroy { VolumeKeyBridge.attached = false; VolumeKeyBridge.emit = null }
  }
}
