import { validateTitle } from "./validation.mjs";

const form = document.querySelector("form");
const input = document.querySelector("input");
const error = document.querySelector("[role=alert]");
const list = document.querySelector("ul");

async function load() {
  const response = await fetch("/api/items");
  const { items } = await response.json();
  list.replaceChildren(
    ...items.map((item) => {
      const entry = document.createElement("li");
      entry.textContent = `${item.title}${item.completed ? " — complete" : ""}`;
      if (!item.completed) {
        const button = document.createElement("button");
        button.textContent = `Complete ${item.title}`;
        button.onclick = async () => {
          await fetch(`/api/items/${item.id}`, { method: "PATCH" });
          await load();
        };
        entry.append(" ", button);
      }
      return entry;
    }),
  );
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = validateTitle(input.value);
  if (error.textContent) return;
  const response = await fetch("/api/items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: input.value }),
  });
  if (!response.ok) {
    error.textContent = (await response.json()).error;
    return;
  }
  input.value = "";
  await load();
});

await load();
