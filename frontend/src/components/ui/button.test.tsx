import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { Button } from "./button";

test("button exposes its label and handles a staff action", async () => {
  const user = userEvent.setup();
  const onClick = vi.fn();
  render(<Button onClick={onClick}>Одобри за објавување</Button>);

  await user.click(screen.getByRole("button", { name: "Одобри за објавување" }));

  expect(onClick).toHaveBeenCalledOnce();
});
