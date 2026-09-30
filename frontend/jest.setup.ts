import "@testing-library/jest-dom";

// Tests mock fetch with jest.spyOn(global, "fetch"). Replace the real one so a
// request a test forgot to mock fails loudly instead of reaching a network.
Object.defineProperty(globalThis, "fetch", {
  configurable: true,
  writable: true,
  value: () => Promise.reject(new Error("fetch was called without being mocked in this test")),
});
