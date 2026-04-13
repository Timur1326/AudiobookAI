import axios from "axios";
import { getToken } from "../auth";

const api = axios.create({ baseURL: "http://localhost:8000" });

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
export const deleteBook    = (book)                       => api.delete(`/books/${book}`);
export const getBook       = (book)                       => api.get(`/books/${book}`);
export const getChapter    = (book, id)                   => api.get(`/books/${book}/chapters/${id}`);
export const updateSpeaker = (book, chId, pIdx, speaker)  =>
  api.put(`/books/${book}/chapters/${chId}/paragraphs/${pIdx}/speaker`, { speaker });
export const getSpeakers   = (book, chId)                 => api.get(`/books/${book}/chapters/${chId}/speakers`);
export const getCharacters        = (book)                      => api.get(`/books/${book}/characters`);
export const importCharacters     = (book)                      => api.post(`/books/${book}/characters/import`);
export const updateCharacterVoice = (book, charId, voice_id, engine) =>
  api.put(`/books/${book}/characters/${charId}/voice`, { voice_id, engine });
export const listVoices           = (book, engine)              => api.get(`/books/${book}/voices?engine=${engine}`);
export const assignVoices         = (book, engine)              => api.post(`/books/${book}/assign-voices?engine=${engine}`);
export const previewVoice         = (book, text, voice_id, engine) =>
  api.post(`/books/${book}/preview-voice`, { text, voice_id, engine }, { responseType: "blob" });
export const synthesize         = (book, data)                    => api.post(`/books/${book}/synthesize`, data);
export const runPipeline        = (book, steps, engine)           => api.post(`/books/${book}/pipeline/run`, { steps, engine });
export const synthesizeBatch    = (book, chapter_ids, engine, narrator_style = "standard") => api.post(`/books/${book}/synthesize-batch`, { chapter_ids, engine, narrator_style });
export const getAudioUrl        = (book, chId, engine)            =>
  `http://localhost:8000/books/${book}/audio/${chId}?engine=${engine}`;
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

export const authRegister = (email, password) => api.post("/auth/register", { email, password });
export const authLogin    = (email, password) => api.post("/auth/login",    { email, password });
export const authMe       = ()                => api.get("/auth/me");