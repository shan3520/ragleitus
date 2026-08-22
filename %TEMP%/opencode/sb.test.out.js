var import_react2 = require("@testing-library/react");
var import_SearchBar = require("./SearchBar");
const paginatedResponse = (count, total) => ({
  ok: true,
  json: () => Promise.resolve({
    items: Array.from({ length: count }, (_, i) => ({
      id: `doc_${i + 1}`,
      name: `Doc ${i + 1}`
    })),
    total
  })
});
describe("SearchBar", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });
  it("renders selector and passes correct group_id", () => {
    const handleSearch = jest.fn();
    const groups = [{ id: "group_1", name: "Group One" }];
    (0, import_react2.render)(<import_SearchBar.SearchBar onSearch={handleSearch} groups={groups} />);
    const selector = import_react2.screen.getByTestId("group-selector");
    expect(selector).toBeInTheDocument();
    import_react2.fireEvent.change(selector, { target: { value: "group_1" } });
    const button = import_react2.screen.getByTestId("search-button");
    import_react2.fireEvent.click(button);
    expect(handleSearch).toHaveBeenCalledWith("", "group_1");
  });
  it('passes undefined when "Search All" is selected', () => {
    const handleSearch = jest.fn();
    const groups = [{ id: "group_1", name: "Group One" }];
    (0, import_react2.render)(<import_SearchBar.SearchBar onSearch={handleSearch} groups={groups} />);
    const selector = import_react2.screen.getByTestId("group-selector");
    import_react2.fireEvent.change(selector, { target: { value: "" } });
    const button = import_react2.screen.getByTestId("search-button");
    import_react2.fireEvent.click(button);
    expect(handleSearch).toHaveBeenCalledWith("", void 0);
  });
  it("renders results when the API returns a flat array", async () => {
    const handleSearch = jest.fn();
    const groups = [{ id: "group_1", name: "Group One" }];
    jest.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([{ id: "doc_1", name: "Legacy Flat Result" }])
    });
    (0, import_react2.render)(<import_SearchBar.SearchBar onSearch={handleSearch} groups={groups} />);
    import_react2.fireEvent.click(import_react2.screen.getByTestId("search-button"));
    expect(await import_react2.screen.findByText("Legacy Flat Result")).toBeInTheDocument();
    expect(import_react2.screen.getByTestId("search-results").children).toHaveLength(1);
  });
  it("extracts items when the API returns a paginated object", async () => {
    const handleSearch = jest.fn();
    const groups = [{ id: "group_1", name: "Group One" }];
    jest.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        items: [{ id: "doc_2", name: "Paginated Result" }],
        total: 1
      })
    });
    (0, import_react2.render)(<import_SearchBar.SearchBar onSearch={handleSearch} groups={groups} />);
    import_react2.fireEvent.click(import_react2.screen.getByTestId("search-button"));
    expect(await import_react2.screen.findByText("Paginated Result")).toBeInTheDocument();
    expect(import_react2.screen.getByTestId("search-results").children).toHaveLength(1);
  });
  it("requests the next page from the API when Next is clicked", async () => {
    const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue(paginatedResponse(20, 45));
    (0, import_react2.render)(<import_SearchBar.SearchBar onSearch={jest.fn()} groups={[]} />);
    import_react2.fireEvent.click(import_react2.screen.getByTestId("search-button"));
    await import_react2.screen.findByText("Doc 1");
    expect(String(fetchMock.mock.calls[0][0])).toContain("skip=0&limit=20");
    import_react2.fireEvent.click(import_react2.screen.getByTestId("next-button"));
    await (0, import_react2.waitFor)(() => expect(fetchMock.mock.calls.length).toBe(2));
    expect(String(fetchMock.mock.calls[1][0])).toContain("skip=20&limit=20");
  });
  it("resets the requested page to 1 when the page size changes", async () => {
    const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue(paginatedResponse(20, 120));
    (0, import_react2.render)(<import_SearchBar.SearchBar onSearch={jest.fn()} groups={[]} />);
    import_react2.fireEvent.click(import_react2.screen.getByTestId("search-button"));
    await import_react2.screen.findByText("Doc 1");
    import_react2.fireEvent.click(import_react2.screen.getByTestId("next-button"));
    await (0, import_react2.waitFor)(() => expect(fetchMock.mock.calls.length).toBe(2));
    expect(String(fetchMock.mock.calls[1][0])).toContain("skip=20&limit=20");
    import_react2.fireEvent.change(import_react2.screen.getByTestId("page-size-selector"), {
      target: { value: "50" }
    });
    await (0, import_react2.waitFor)(() => expect(fetchMock.mock.calls.length).toBe(3));
    expect(String(fetchMock.mock.calls[2][0])).toContain("skip=0&limit=50");
    expect(String(fetchMock.mock.calls[2][0])).not.toContain("skip=50");
    expect(String(fetchMock.mock.calls[2][0])).not.toContain("skip=100");
  });
  it("computes the displayed range bounds in the summary", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(paginatedResponse(20, 45));
    (0, import_react2.render)(<import_SearchBar.SearchBar onSearch={jest.fn()} groups={[]} />);
    import_react2.fireEvent.click(import_react2.screen.getByTestId("search-button"));
    expect(await import_react2.screen.findByText("Showing 1-20 of 45")).toBeInTheDocument();
    import_react2.fireEvent.click(import_react2.screen.getByTestId("next-button"));
    expect(await import_react2.screen.findByText("Showing 21-40 of 45")).toBeInTheDocument();
  });
  it("resets pagination to page 1 when a new search is submitted", async () => {
    const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue(paginatedResponse(20, 45));
    (0, import_react2.render)(<import_SearchBar.SearchBar onSearch={jest.fn()} groups={[]} />);
    import_react2.fireEvent.change(import_react2.screen.getByTestId("search-input"), {
      target: { value: "first" }
    });
    import_react2.fireEvent.click(import_react2.screen.getByTestId("search-button"));
    await import_react2.screen.findByText("Doc 1");
    import_react2.fireEvent.click(import_react2.screen.getByTestId("next-button"));
    await (0, import_react2.waitFor)(() => expect(fetchMock.mock.calls.length).toBe(2));
    import_react2.fireEvent.change(import_react2.screen.getByTestId("search-input"), {
      target: { value: "second" }
    });
    import_react2.fireEvent.click(import_react2.screen.getByTestId("search-button"));
    await (0, import_react2.waitFor)(() => expect(fetchMock.mock.calls.length).toBe(3));
    expect(String(fetchMock.mock.calls[2][0])).toContain("q=second");
    expect(String(fetchMock.mock.calls[2][0])).toContain("skip=0&limit=20");
    expect(String(fetchMock.mock.calls[2][0])).not.toContain("skip=20&limit=20");
  });
});
