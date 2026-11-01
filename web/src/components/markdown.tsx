import ReactMarkdown from "react-markdown";

/** Render an assistant reply. Raw HTML in the text is not rendered (react-markdown's default). */
export function Markdown({ children }: { children: string }) {
  return <ReactMarkdown>{children}</ReactMarkdown>;
}
