import axios from "axios";
import { getToken } from "../auth";

export const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const api = axios.create({ baseURL: BASE_URL });

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export const getBooks      = ()                           => api.get("/books");
export const uploadBook    = (file)                       => {
  const form = new FormData();
  form.append("file", file);
  return api.post("/books/upload", form, { headers: { "Content-Type": "multipart/form-data" } });
};
export const deleteBook    = (book)                      => api.delete(`/books/${book}`);
export const getBook       = (book)                       => api.get(`/books/${book}`);
export const getCharacters        = (book)                      => api.get(`/books/${book}/characters`);
export const updateCharacterVoice = (book, charId, voice_id, engine) =>
  api.put(`/books/${book}/characters/${charId}/voice`, { voice_id, engine });
export const listVoices           = (book, engine)              => api.get(`/books/${book}/voices?engine=${engine}`);
export const previewVoice         = (book, text, voice_id, engine) =>
  api.post(`/books/${book}/preview-voice`, { text, voice_id, engine }, { responseType: "blob" });
export const synthesize         = (book, data)                    => api.post(`/books/${book}/synthesize`, data);
export const runPipeline        = (book, steps, engine)           => api.post(`/books/${book}/pipeline/run`, { steps, engine });
export const synthesizeBatch    = (book, chapter_ids, engine, narrator_style = "standard") => api.post(`/books/${book}/synthesize-batch`, { chapter_ids, engine, narrator_style });
export const getAudioUrl        = (book, chId, engine)            =>
  `${BASE_URL}/books/${book}/audio/${chId}?engine=${engine}`;
export const getTimestamps      = (book, chId, engine)            =>
  api.get(`/books/${book}/chapters/${chId}/timestamps?engine=${engine}`);
export const getChapterReader   = (book, chId, engine)            =>
  api.get(`/books/${book}/chapters/${chId}/reader?engine=${engine}`);
export const getAmbientConfig   = (book, chId, engine)            =>
  api.get(`/books/${book}/chapters/${chId}/ambient?engine=${engine}`);
export const generateAmbient    = (book, chId, engine)            =>
  api.post(`/books/${book}/chapters/${chId}/ambient/generate?engine=${engine}`);
export const searchGutenberg    = (q, page = 1)                   => api.get(`/books/gutenberg/search?q=${encodeURIComponent(q)}&page=${page}`);
export const importGutenberg    = (data)                          => api.post(`/books/gutenberg/import`, data);
export const searchAmbient      = (book, q)                       => api.get(`/books/${book}/ambient/search?q=${encodeURIComponent(q)}`);
export const assignAmbient      = (book, chId, sound_id, preview_url, engine) =>
  api.post(`/books/${book}/chapters/${chId}/ambient/assign`, { sound_id, preview_url, engine });
export const assignSceneAmbient = (book, sceneId, sound_id, preview_url, engine) =>
  api.post(`/books/scenes/${sceneId}/ambient/assign`, { sound_id, preview_url, engine });

export const authRegister = (email, password) => api.post("/auth/register", { email, password });
export const authLogin    = (email, password) => api.post("/auth/login",    { email, password });
export const authMe       = ()                => api.get("/auth/me");