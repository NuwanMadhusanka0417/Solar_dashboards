import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { type Meta, type Site, useApi } from "./api";
import { Async, Icon } from "./components/ui";
import { MetaContext } from "./context";
import AllSites from "./pages/AllSites";
import SiteDashboard from "./pages/SiteDashboard";

function Sidebar({ meta }: { meta: Meta }) {
  const { search } = useLocation();
  // Keep the date range when switching pages; drop the campus filter.
  const keep = new URLSearchParams(search);
  keep.delete("campus");
  const q = keep.toString() ? `?${keep}` : "";
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-icon">{Icon.leaf}</div>
        <div>
          <div className="brand-title">La Trobe Solar</div>
          <div className="brand-sub">LEAP</div>
        </div>
      </div>
      <div className="nav-section">Energy</div>
      <NavLink to={`/${q}`} end className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
        {Icon.grid} Solar
      </NavLink>
      <NavLink to={`/site${q}`} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
        {Icon.grid} Individual Solar
      </NavLink>
      <div className="sidebar-foot">
        Data to {meta.data_end}
        <br />
        Processed {meta.generated_at.slice(0, 16).replace("T", " ")}
      </div>
    </aside>
  );
}

function SiteRedirect({ sites }: { sites: Site[] }) {
  const { search } = useLocation();
  const key = sites.find((s) => s.site_key === "library")?.site_key ?? sites[0]?.site_key;
  return <Navigate to={`/site/${key}${search}`} replace />;
}

export default function App() {
  const meta = useApi<Meta>("/meta");
  const sites = useApi<Site[]>("/sites");
  return (
    <Async state={{ data: meta.data && sites.data ? { meta: meta.data, sites: sites.data } : null, error: meta.error ?? sites.error, loading: meta.loading || sites.loading }} height={400}>
      {(ctx) => (
        <MetaContext.Provider value={ctx}>
          <div className="app">
            <Sidebar meta={ctx.meta} />
            <main className="main">
              <Routes>
                <Route path="/" element={<AllSites />} />
                <Route path="/site" element={<SiteRedirect sites={ctx.sites} />} />
                <Route path="/site/:key" element={<SiteDashboard />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </main>
          </div>
        </MetaContext.Provider>
      )}
    </Async>
  );
}
