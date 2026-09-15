export function validateTitle(value) {
  const title = value.trim();
  if (!title) return "Title is required";
  if (title.length > 80) return "Title must be 80 characters or fewer";
  return "";
}
