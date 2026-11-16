// @vitest-environment jsdom
// Requirement 6.3: English and French strings live in en.json / fr.json.
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ExerciseCard } from "../components/ExerciseCard";
import { Chat } from "../components/Chat";
import { useStore } from "../store";
import en from "./en.json";
import fr from "./fr.json";
import { DICTS, detectLang, setLang, setSessionLang, t } from "./index";

beforeEach(() => {
  Element.prototype.scrollIntoView = () => {};
  setLang("en");
});
afterEach(() => {
  cleanup();
  setLang("en");
});

describe("dictionaries", () => {
  it("en.json and fr.json have the same keys", () => {
    expect(Object.keys(fr).sort()).toEqual(Object.keys(en).sort());
  });
  it("no value is empty", () => {
    for (const [name, d] of Object.entries({ en, fr }))
      for (const [k, v] of Object.entries(d))
        expect(v.trim(), `${name}:${k}`).not.toBe("");
  });
  it("placeholders match between languages", () => {
    const ph = (s: string) =>
      [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const k of Object.keys(en))
      expect(ph((fr as Record<string, string>)[k] ?? ""), k).toEqual(
        ph((en as Record<string, string>)[k] ?? ""),
      );
  });
});

describe("t", () => {
  it("interpolates parameters", () => {
    expect(t("exercise.step", { step: 2, total: 5 })).toBe("Step 2 of 5");
    setLang("fr");
    expect(t("exercise.step", { step: 2, total: 5 })).toBe("Étape 2 sur 5");
  });
  it("leaves an unknown placeholder untouched", () => {
    expect(t("exercise.step", { step: 2 })).toBe("Step 2 of {total}");
  });
  it("falls back to English for a key missing from the current language, then to the key", () => {
    const saved = (DICTS.fr as Record<string, string>)["chat.send"];
    delete (DICTS.fr as Record<string, string>)["chat.send"];
    try {
      setLang("fr");
      expect(t("chat.send")).toBe("Send");
      expect(t("no.such.key")).toBe("no.such.key");
    } finally {
      (DICTS.fr as Record<string, string>)["chat.send"] = saved ?? "";
    }
  });
  it("language: session fr/en wins, other session languages are ignored, ?lang= is read", () => {
    setSessionLang("fr");
    expect(t("chat.send")).toBe("Envoyer");
    setSessionLang("de");
    expect(t("chat.send")).toBe("Send");
    window.history.replaceState(null, "", "/?lang=fr");
    expect(detectLang()).toBe("fr");
    window.history.replaceState(null, "", "/");
  });
});

describe("French rendering", () => {
  beforeEach(() => {
    useStore.setState({
      transcript: [],
      lesson: {
        lesson_id: "l",
        title: "Modificateurs",
        status: "running",
        step: 2,
        total: 5,
      },
      exercise: {
        exercise_id: "e",
        prompt: "Ajoutez un modificateur",
        skills: [],
        status: "active",
        attempts: 1,
        max_attempts: 3,
        hints_used: 0,
        hints_total: 2,
      },
      clarification: null,
      explore: null,
      status: "idle",
      connected: true,
      send: () => true,
    });
  });
  it("ExerciseCard and Chat follow the Core's session language", () => {
    const { rerender } = render(
      <>
        <Chat />
      </>,
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toBeTruthy();
    // The language arrives with session.state: mounted components switch without a reload.
    act(() => useStore.getState().handle({
        type: "session.state",
        session_id: "s",
        lang: "fr",
        active_adapter: null,
        llm: "scripted",
        model: null,
        profile: null,
      } as never));
    expect(
      screen.getByRole("log", { name: "Historique de la conversation" }),
    ).toBeTruthy();
    expect(
      screen.getAllByText("Posez une question sur votre projet").length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Envoyer" })).toBeTruthy();
    expect(screen.getByText("Étape 2 sur 5")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Indice" })).toBeTruthy();
    expect(screen.getByText(/Tentatives 1\/3 · indices 0\/2/)).toBeTruthy();
    rerender(<ExerciseCard />);
    expect(screen.getByRole("button", { name: "J'ai terminé" })).toBeTruthy();
  });
});
