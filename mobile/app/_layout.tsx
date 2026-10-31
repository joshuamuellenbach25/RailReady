import { QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import { LogBox, StyleSheet } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { useEffect, useState } from "react";
import { AuthProvider } from "@/src/auth";
import { crumb, flushCrumbs } from "@/src/crumbs";
import { ErrorBoundary } from "@/src/components/error-boundary";
import { queryClient } from "@/src/query-client";
import { onRemount } from "@/src/reload";
import { SendQueue } from "@/src/queue";
import "@/src/background"; // defines the OS background send task at module scope (dev/prod builds only)

LogBox.ignoreAllLogs(true);

export default function RootLayout() {
  const [gen, setGen] = useState(0); // safe-reload fallback: bump = re-mount root + re-hydrate auth
  useEffect(() => {
    crumb("app.boot").then(() => flushCrumbs()); // the step after a settings.reload.native crumb shows whether reload reached boot
    return onRemount(() => setGen((g) => g + 1));
  }, []);
  return (
    <GestureHandlerRootView style={styles.root}>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <KeyboardProvider>
            <AuthProvider key={gen}>
              <Stack screenOptions={{ headerShown: false }} />
              <SendQueue />
            </AuthProvider>
          </KeyboardProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
