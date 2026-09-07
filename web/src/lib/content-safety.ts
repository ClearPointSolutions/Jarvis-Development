// Prevent invisible direction overrides and control characters from disguising
// filenames, event messages, and error text. React performs HTML escaping.
export function safeDisplayText(value: string): string {
  return value.replace(
    /[\u0000-\u0008\u000B-\u001F\u007F-\u009F\u202A-\u202E\u2066-\u2069]/g,
    "",
  );
}
export function safeFilename(value: string): string {
  return (
    safeDisplayText(value)
      .replaceAll("\\", "/")
      .split("/")
      .at(-1)
      ?.slice(0, 255) || "unnamed artifact"
  );
}
