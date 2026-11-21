import type { ChatMetadata } from "./api";

export type ChatItem =
  | { id: string; kind: "user"; content: string; failed?: boolean }
  | { id: string; kind: "assistant"; content: string; metadata: ChatMetadata }
  | { id: string; kind: "error"; content: string; status: number | null; retry: RetryArgs };

export interface RetryArgs {
  message: string;
  userItemId: string;
}
