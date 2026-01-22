
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";

export const schemaMarkdown = {
  ...defaultSchema,
  tagNames: [
    ...(defaultSchema.tagNames || []),
    "b",
    "br",
    "strong",
    "em",
    "ul",
    "li",
    "p"
  ],
};