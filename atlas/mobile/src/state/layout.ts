import { useWindowDimensions } from "react-native";
import { isWide } from "../lib/layout";

export function useIsWide(): boolean {
  return isWide(useWindowDimensions().width);
}
