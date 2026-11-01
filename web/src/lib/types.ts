import type { UIMessage } from "ai";

export type ToolStep = {
  name: string;
  label: string;
  status: "running" | "done" | "error";
};

export type ApprovalInfo = {
  id: string;
  toolName: string;
  summary: string;
  status: "pending" | "approved" | "rejected" | "executed" | "failed";
};

/** Chat messages, with the agent's tool steps, approvals and sources as data parts. */
export type SupportUIMessage = UIMessage<
  never,
  {
    tool: ToolStep;
    approval: ApprovalInfo;
    sources: { items: string[] };
    notice: { message: string };
    status: { text: string }; // transient: "Thinking", shown while waiting
    conversation: { status: ConversationStatus }; // transient: sent when a turn ends
  }
>;

export type ConversationStatus = "active" | "awaiting_approval";

export type Customer = { id: string; name: string; email: string };

/** One item of the transcript returned by GET /conversations/{id}. */
export type TranscriptItem =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string; sources: string[] }
  | {
      role: "tool";
      name: string;
      label: string;
      approval?: { id: string; status: ApprovalInfo["status"]; summary: string };
    };

export type Conversation = {
  id: string;
  status: ConversationStatus;
  customer: Customer;
  items: TranscriptItem[];
};

export type ApprovalRequest = {
  id: string;
  conversation_id: string;
  tool_name: "issue_refund" | "send_email";
  tool_input: Record<string, unknown>;
  summary: string;
  status: ApprovalInfo["status"];
  reviewer: string | null;
  reviewer_note: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  decided_at: string | null;
  customer_email: string | null;
};
