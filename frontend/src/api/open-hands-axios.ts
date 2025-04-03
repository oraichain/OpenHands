import axios from "axios";

console.log(
  "import.meta.env.VITE_BACKEND_BASE_URL",
  import.meta.env.VITE_BACKEND_BASE_URL,
);

export const openHands = axios.create({
  baseURL: `${window.location.protocol}//${import.meta.env.VITE_BACKEND_BASE_URL || window?.location.host}`,
});
