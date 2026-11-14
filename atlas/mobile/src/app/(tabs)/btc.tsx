import React from "react";
import { AssetView } from "../../components/AssetView";
import { BTC_ID } from "../../state/selection";

/** Bitcoin has its own tab: the same research view as any asset, opened straight away. */
export default function BtcScreen() {
  return <AssetView id={BTC_ID} hideBack />;
}
