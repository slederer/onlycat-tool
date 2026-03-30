import { createUseCallTool, createUseToolInfo } from "skybridge/web";
import type { AppType } from "../../server/src/index.js";

export const useToolInfo = createUseToolInfo<AppType>();
export const useCallTool = createUseCallTool<AppType>();

export type Output<T extends Parameters<typeof useToolInfo>[0]> = NonNullable<
  ReturnType<typeof useToolInfo<T>>["output"]
>["structuredContent"];
