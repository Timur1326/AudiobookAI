import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Spin, Typography, Button, Card, Tag, Select,
  Input, message, Tooltip, Empty,
} from "antd";
import {
  ArrowLeftOutlined, PlayCircleOutlined, LoadingOutlined,
  SearchOutlined, UserOutlined,
} from "@ant-design/icons";
import { getCharacters, listVoices, updateCharacterVoice, previewVoice } from "../api/client";

const { Title, Text } = Typography;

const GENDER_COLOR = { male: "blue", female: "pink", unknown: "default" };

export default function CharactersPage() {
  const { book }   = useParams();
  const navigate   = useNavigate();

  const [characters, setCharacters] = useState([]);
  const [voices,     setVoices]     = useState([]);
  const [loading,    setLoading]    = useState(true);
  const [search,     setSearch]     = useState("");
  const [playing,    setPlaying]    = useState(null);
  const audioRef = useRef(null);

  useEffect(() => {
    Promise.all([getCharacters(book), listVoices(book, "elevenlabs")])
      .then(([cRes, vRes]) => {
        setCharacters(cRes.data.characters ?? []);
        setVoices(vRes.data.voices ?? []);
      })
      .catch(() => message.error("Failed to load characters"))
      .finally(() => setLoading(false));
  }, [book]);

  const handleVoiceChange = async (charId, voiceId) => {
    try {
      await updateCharacterVoice(book, charId, voiceId, "elevenlabs");
      setCharacters(prev =>
        prev.map(c => c.id === charId ? { ...c, voice_id: voiceId } : c)
      );
    } catch {
      message.error("Failed to update voice");
    }
  };

  const handlePreview = async (char) => {
    if (!char.voice_id) return message.warning("Assign a voice first");
    const text = char.sample_text || `Hello, I am ${char.name}.`;
    setPlaying(char.id);
    try {
      const r = await previewVoice(book, text, char.voice_id, "elevenlabs");
      const url = URL.createObjectURL(r.data);
      if (audioRef.current) audioRef.current.pause();
      audioRef.current = new Audio(url);
      audioRef.current.play();
      audioRef.current.onended = () => setPlaying(null);
    } catch {
      message.error("Preview failed");
      setPlaying(null);
    }
  };

  const filtered = characters.filter(c =>
    c.name.toLowerCase().includes(search.toLowerCase()) ||
    c.aliases?.some(a => a.toLowerCase().includes(search.toLowerCase()))
  );

  const voiceOptions = voices.map(v => ({
    value: v.voice_id || v.id,
    label: v.name,
  }));

  if (loading) return (
    <div style={{ textAlign: "center", paddingTop: 120 }}>
      <Spin size="large" />
    </div>
  );

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "36px 24px" }}>

      {/* Header */}
      <Button
        icon={<ArrowLeftOutlined />}
        style={{ marginBottom: 24 }}
        onClick={() => navigate(`/books/${book}`)}
      >
        Back to book
      </Button>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
        <div>
          <Title level={2} style={{ margin: 0 }}>Characters</Title>
          <Text type="secondary">{characters.length} characters extracted</Text>
        </div>
        <Input
          prefix={<SearchOutlined style={{ color: "#9ca3af" }} />}
          placeholder="Search by name"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width: 240 }}
          allowClear
        />
      </div>

      {filtered.length === 0 && (
        <Empty
          description={search ? "No characters match your search" : "No characters found. Run pipeline first."}
          style={{ paddingTop: 60 }}
        />
      )}

      {/* Character cards */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {filtered.map(char => {
          const voiceName = voices.find(v => (v.voice_id || v.id) === char.voice_id)?.name;

          return (
            <Card
              key={char.id}
              style={{ borderRadius: 12 }}
              styles={{ body: { padding: "20px 24px" } }}
            >
              <div style={{ display: "flex", gap: 16 }}>

                {/* Avatar */}
                <div style={{
                  width: 48, height: 48, borderRadius: 12, flexShrink: 0,
                  background: "#e8f4f7", display: "flex",
                  alignItems: "center", justifyContent: "center", fontSize: 22,
                }}>
                  <UserOutlined style={{ color: "#5a9dad" }} />
                </div>

                {/* Main info */}
                <div style={{ flex: 1, minWidth: 0 }}>

                  {/* Name + tags */}
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
                    <Text strong style={{ fontSize: 16 }}>{char.name}</Text>
                    {char.gender && (
                      <Tag color={GENDER_COLOR[char.gender?.toLowerCase()] ?? "default"} style={{ margin: 0 }}>
                        {char.gender}
                      </Tag>
                    )}
                    {char.age && (
                      <Tag style={{ margin: 0 }}>{char.age}</Tag>
                    )}
                  </div>

                  {/* Personality / description */}
                  {char.personality && (
                    <Text type="secondary" style={{ fontSize: 13, display: "block", marginBottom: 8 }}>
                      {char.personality}
                    </Text>
                  )}

                  {/* Aliases */}
                  {char.aliases?.length > 0 && (
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>Also known as:</Text>
                      {char.aliases.map(a => (
                        <Tag key={a} style={{ margin: 0, fontSize: 12 }}>{a}</Tag>
                      ))}
                    </div>
                  )}

                  {/* Sample quote */}
                  {char.sample_text && (
                    <Text
                      italic
                      type="secondary"
                      style={{ fontSize: 12, display: "block", marginBottom: 12 }}
                    >
                      "{char.sample_text.slice(0, 120)}{char.sample_text.length > 120 ? "..." : ""}"
                    </Text>
                  )}

                  {/* Voice selector + preview */}
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Select
                      value={char.voice_id || undefined}
                      placeholder="— select voice —"
                      options={voiceOptions}
                      onChange={val => handleVoiceChange(char.id, val)}
                      style={{ width: 200 }}
                      size="small"
                      showSearch
                      filterOption={(input, opt) =>
                        opt.label.toLowerCase().includes(input.toLowerCase())
                      }
                    />
                    <Tooltip title={voiceName ? `Preview: ${voiceName}` : "Assign a voice first"}>
                      <Button
                        size="small"
                        icon={playing === char.id ? <LoadingOutlined /> : <PlayCircleOutlined />}
                        onClick={() => handlePreview(char)}
                        disabled={!char.voice_id || (playing !== null && playing !== char.id)}
                      />
                    </Tooltip>
                    {voiceName && (
                      <Text type="secondary" style={{ fontSize: 12 }}>{voiceName}</Text>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}