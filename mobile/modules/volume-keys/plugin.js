// Config plugin: injects a dispatchKeyEvent override into MainActivity that forwards volume keys to the local
// RailReadyVolumeKeys module (consumed only while the in-app camera has attached it). Idempotent.
const { withMainActivity } = require("@expo/config-plugins");

const MARK = "// railready-volume-keys";

module.exports = function withVolumeKeys(config) {
  return withMainActivity(config, (cfg) => {
    let src = cfg.modResults.contents;
    if (src.includes(MARK)) return cfg;
    const isKotlin = cfg.modResults.language === "kt";
    if (!isKotlin) throw new Error("railready-volume-keys: MainActivity must be Kotlin");
    src = src.replace(/(import [^\n]+\n)/, `$1import android.view.KeyEvent\nimport expo.modules.railreadyvolumekeys.VolumeKeyBridge\n`);
    src = src.replace(/class MainActivity[^{]*\{/, (m) => `${m}\n  ${MARK}\n  override fun dispatchKeyEvent(event: KeyEvent): Boolean {\n    if (VolumeKeyBridge.handle(event)) return true\n    return super.dispatchKeyEvent(event)\n  }\n`);
    cfg.modResults.contents = src;
    return cfg;
  });
};
