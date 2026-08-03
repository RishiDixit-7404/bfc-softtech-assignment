import "@testing-library/jest-dom/vitest";

// Deliberately *not* stubbing scrollIntoView. jsdom does not implement it, and
// a stub here would hide the fact that an effect throwing takes the whole tree
// down with it - which is exactly what it did hide, until the committed bundle
// was booted in a DOM that had no stub and rendered nothing at all.
// Transcript.tsx now guards the call, so the missing method is harmless and the
// tests exercise the same code path a real browser does.

if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}
