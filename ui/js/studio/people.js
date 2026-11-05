// The studio team as friendly illustrated people (from the design mock-up, j2-revamp/design-directions/people.js).
// avatar(key, size, {prop}) returns an inline SVG string built only from the fixed table below (no outside text).

export const TEAM = {
  asha:  { name: "Asha",  role: "Project lead", skin: "#E8B48F", hair: "#2B1D16", style: "bun",   shirt: "#3D5A80", prop: "chat" },
  mira:  { name: "Mira",  role: "Writer",       skin: "#F1C7A5", hair: "#7A3E1D", style: "long",  shirt: "#C8553D", prop: "pen" },
  kabir: { name: "Kabir", role: "Designer",     skin: "#C98E68", hair: "#1E1E1E", style: "short", shirt: "#2A9D8F", prop: "palette" },
  dev:   { name: "Dev",   role: "Builder",      skin: "#B07A55", hair: "#151515", style: "curly", shirt: "#E9A23B", prop: "wrench" },
  nora:  { name: "Nora",  role: "Checker",      skin: "#F3D2B6", hair: "#B5651D", style: "bob",   shirt: "#6D597A", prop: "glass" },
};

function hairShape(p) {
  const h = p.hair;
  switch (p.style) {
    case "bun":   return `<circle cx="32" cy="9" r="6" fill="${h}"/><path d="M18 26c0-10 6-15 14-15s14 5 14 15c-3-5-8-7-14-7s-11 2-14 7z" fill="${h}"/>`;
    case "long":  return `<path d="M17 28c0-11 6-17 15-17s15 6 15 17v14c-3 2-5 2-6 0V27c-3-4-6-5-9-5s-6 1-9 5v15c-1 2-3 2-6 0z" fill="${h}"/>`;
    case "short": return `<path d="M19 25c-1-9 5-14 13-14s14 4 13 14c-2-4-6-6-13-6s-11 2-13 6z" fill="${h}"/>`;
    case "curly": return [[22,17],[28,13],[35,13],[41,17],[20,23],[44,23]].map(([x,y]) => `<circle cx="${x}" cy="${y}" r="5.5" fill="${h}"/>`).join("");
    case "bob":   return `<path d="M18 30c-1-12 5-19 14-19s15 7 14 19h-5c0-5-1-9-3-11-3 2-8 3-15 3-1 2-1 5-1 8z" fill="${h}"/>`;
  }
  return "";
}

function propShape(p) {
  switch (p.prop) {
    case "pen":     return `<rect x="46" y="44" width="4" height="15" rx="1.5" transform="rotate(30 48 51)" fill="#F4D35E" stroke="#2b2b2b" stroke-width="1"/>`;
    case "palette": return `<ellipse cx="50" cy="52" rx="8" ry="6" fill="#F6E7CB" stroke="#2b2b2b" stroke-width="1"/><circle cx="47" cy="50" r="1.6" fill="#E76F51"/><circle cx="51" cy="49" r="1.6" fill="#2A9D8F"/><circle cx="54" cy="52" r="1.6" fill="#3D5A80"/>`;
    case "wrench":  return `<path d="M44 58l9-9m0 0a4 4 0 1 0 3-3" stroke="#5c6670" stroke-width="3.2" stroke-linecap="round" fill="none"/>`;
    case "glass":   return `<circle cx="50" cy="50" r="5.5" fill="#dff1f7" stroke="#2b2b2b" stroke-width="1.6"/><path d="M54 54l5 5" stroke="#2b2b2b" stroke-width="2.4" stroke-linecap="round"/>`;
    case "chat":    return `<path d="M43 44h14a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-8l-4 3v-3h-2a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3z" fill="#fff" stroke="#2b2b2b" stroke-width="1.1"/><circle cx="46" cy="50" r="1" fill="#2b2b2b"/><circle cx="50" cy="50" r="1" fill="#2b2b2b"/><circle cx="54" cy="50" r="1" fill="#2b2b2b"/>`;
  }
  return "";
}

export function avatar(key, size = 44, opts = {}) {
  const p = TEAM[key];
  const back = p.style === "long" || p.style === "bob" ? hairShape(p) : "";
  return `<svg class="av" width="${size}" height="${size}" viewBox="0 0 64 64" aria-label="${p.name}, ${p.role}">
    ${opts.ring === false ? "" : `<circle cx="32" cy="32" r="31" fill="${opts.bg || "#F7F2EA"}"/>`}
    ${back}
    <path d="M12 64c1-11 9-17 20-17s19 6 20 17z" fill="${p.shirt}"/>
    <rect x="28" y="38" width="8" height="9" rx="3" fill="${p.skin}"/>
    <circle cx="32" cy="27" r="13" fill="${p.skin}"/>
    ${back ? "" : hairShape(p)}
    ${p.style === "long" || p.style === "bob" ? `<path d="M20 24c3-4 7-5 12-5s9 1 12 5c-1-7-6-11-12-11s-11 4-12 11z" fill="${p.hair}"/>` : ""}
    <circle cx="27.5" cy="28" r="1.6" fill="#2b2b2b"/><circle cx="36.5" cy="28" r="1.6" fill="#2b2b2b"/>
    <path d="M28 33c2 2 6 2 8 0" stroke="#2b2b2b" stroke-width="1.5" fill="none" stroke-linecap="round"/>
    <circle cx="24.5" cy="32" r="2.2" fill="#E8836B" opacity=".35"/><circle cx="39.5" cy="32" r="2.2" fill="#E8836B" opacity=".35"/>
    ${opts.prop === false ? "" : propShape(p)}
  </svg>`;
}
