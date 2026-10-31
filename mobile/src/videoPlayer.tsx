// REQ-1245: video playback on the phone. Local file before sending; the private server copy (HTTP Range) after.
// Seeking: `seek` carries a nonce so tapping the same finding twice seeks again; applied in an effect, never during render.
import { useVideoPlayer, VideoView } from "expo-video";
import { useEffect } from "react";
import { View } from "react-native";

export type Seek = { t: number; n: number } | null;

export function VideoPlayer({ uri, token, seek, testID }: { uri: string; token?: string | null; seek?: Seek; testID?: string }) {
  const remote = uri.startsWith("http");
  const player = useVideoPlayer(remote && token ? { uri, headers: { Authorization: `Bearer ${token}` } } : { uri }, (p) => {
    p.loop = false;
  });
  useEffect(() => {
    if (!seek || !player) return;
    try {
      player.currentTime = seek.t;
      player.pause();
    } catch {
      /* player not ready yet: the next tap seeks */
    }
  }, [seek, player]);
  // Video chrome is black in both themes on purpose (letterboxing around footage).
  return (
    <View testID={testID} style={{ width: "100%", aspectRatio: 16 / 9, backgroundColor: "#000", borderRadius: 12, overflow: "hidden" }}>
      <VideoView player={player} style={{ width: "100%", height: "100%" }} nativeControls contentFit="contain" />
    </View>
  );
}
