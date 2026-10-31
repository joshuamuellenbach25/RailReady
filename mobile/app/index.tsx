import { Redirect } from "expo-router";
import { View } from "react-native";
import { useAuth } from "@/src/auth";
import { Loading } from "@/src/ui";
import { useTheme } from "@/src/theme";

export default function Index() {
  const { user } = useAuth();
  const { colors } = useTheme();
  if (user === null)
    return (
      <View style={{ flex: 1, backgroundColor: colors.surface, justifyContent: "center" }}>
        <Loading text="Authenticating..." />
      </View>
    );
  if (user === false) return <Redirect href="/login" />;
  return <Redirect href={user.role === "foreman" ? "/home" : "/office"} />;
}
