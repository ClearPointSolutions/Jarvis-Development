import assert from "node:assert/strict";
import test from "node:test";
import { validateTitle } from "./validation.mjs";

test("validates required and bounded titles", () => {
  assert.equal(validateTitle("  "), "Title is required");
  assert.equal(validateTitle("x".repeat(81)), "Title must be 80 characters or fewer");
  assert.equal(validateTitle("Useful item"), "");
});
