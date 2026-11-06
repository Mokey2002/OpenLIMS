import { useEffect, useState } from "react";
import { NavDropdown } from "react-bootstrap";
import { NavLink } from "react-router-dom";
import { favoritesStorageKey, loadFavorites, saveFavorites } from "../utils/favorites";

function AccountFavorites({ userId, storageKey, currentPath, routes, canVisit }) {
  const [favorites, setFavorites] = useState(() => loadFavorites(userId, routes));
  const [saveError, setSaveError] = useState(false);
  const current = Object.hasOwn(routes, currentPath) && canVisit(currentPath) ? currentPath : null;
  const visible = favorites.filter(canVisit);

  useEffect(() => {
    if (!storageKey) return;
    function refresh(event) {
      try {
        if (event.storageArea !== window.localStorage || (event.key !== null && event.key !== storageKey)) return;
      } catch {
        return;
      }
      setFavorites(loadFavorites(userId, routes));
    }
    window.addEventListener("storage", refresh);
    return () => window.removeEventListener("storage", refresh);
  }, [userId, storageKey, routes]);

  function toggle() {
    if (!storageKey || !current) return;
    const next = favorites.includes(current) ? favorites.filter(path => path !== current) : [...favorites, current];
    setFavorites(next);
    setSaveError(!saveFavorites(userId, next, routes));
  }

  return <NavDropdown title={`Favorites${visible.length ? ` (${visible.length})` : ""}`} id="favorites-nav" disabled={!storageKey}>
    {visible.length === 0 && <NavDropdown.Item disabled>No favorites pinned</NavDropdown.Item>}
    {visible.map(path => <NavDropdown.Item as={NavLink} to={path} key={path}>{routes[path]}</NavDropdown.Item>)}
    {current && <><NavDropdown.Divider /><NavDropdown.Item onClick={toggle} disabled={!storageKey}>
      {favorites.includes(current) ? "★ Unpin current page" : "☆ Pin current page"}
    </NavDropdown.Item></>}
    {saveError && <NavDropdown.ItemText role="status">Favorites could not be saved in this browser. Changes will last until you reload.</NavDropdown.ItemText>}
  </NavDropdown>;
}

export default function FavoritesMenu(props) {
  const storageKey = favoritesStorageKey(props.userId);
  // An account change remounts the state before rendering another user's pins.
  return <AccountFavorites key={storageKey || "unidentified"} {...props} storageKey={storageKey} />;
}
