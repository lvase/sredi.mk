import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import { NotFoundPage } from "./NotFoundPage";

test("offers recovery actions from the custom 404 page", () => {
  render(
    <MemoryRouter initialEntries={["/nepostoecka-stranica"]}>
      <NotFoundPage />
    </MemoryRouter>
  );

  expect(screen.getByRole("heading", { name: "Оваа страница не е пронајдена." })).toBeVisible();
  expect(screen.getByRole("link", { name: /На почетна/ })).toHaveAttribute("href", "/");
  expect(screen.getByRole("link", { name: /Избери општина/ })).toHaveAttribute("href", "/");
});
