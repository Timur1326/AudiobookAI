import { useEffect, useState, useRef } from "react";
import {
  Card, Col, Row, Typography, Spin, Empty, Button,
  Tag, Modal, Upload, message, Popconfirm, Tooltip, Input, List, Avatar,
} from "antd";
import {
  BookOutlined, PlusOutlined, DeleteOutlined,
  InboxOutlined, ArrowRightOutlined, SearchOutlined, DownloadOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { getBooks, uploadBook, deleteBook, searchGutenberg, importGutenberg, BASE_URL } from "../api/client";

const { Title, Text } = Typography;
const { Dragger } = Upload;
const { Search } = Input;

const STEP_LABELS = {
  1: "Parse",
  2: "Quotes",
  3: "Scenes",
  4: "Characters",
  5: "Attribution",
  6: "Voices",
  7: "Synthesis",
};

const STATUS_COLOR = {
  done:    "#22c55e",
  running: "#f97316",
  error:   "#ef4444",
  pending: "#d1d5db",
};

function currentStepLabel(steps) {
  if (!steps) return null;
  const entries = Object.entries(steps).map(([k, v]) => ({ step: Number(k), status: v }));
  const running = entries.find(e => e.status === "running");
  if (running) return { label: STEP_LABELS[running.step], color: "#f97316" };
  const error = entries.find(e => e.status === "error");
  if (error) return { label: `Error: step ${error.step}`, color: "#ef4444" };
  const pending = entries.find(e => e.status === "pending");
  if (!pending) return { label: "Complete", color: "#22c55e" };
  const lastDone = [...entries].reverse().find(e => e.status === "done");
  if (!lastDone) return { label: "Not started", color: "#9ca3af" };
  return { label: STEP_LABELS[pending.step], color: "#5a9dad" };
}

function BookCover({ slug }) {
  const [error, setError] = useState(false);
  const src = `${BASE_URL}/books/${slug}/cover`;

  if (error) {
    return (
      <div style={{
        width: 72, height: 100, borderRadius: 8, flexShrink: 0,
        background: "#e8f4f7", display: "flex",
        alignItems: "center", justifyContent: "center",
      }}>
        <BookOutlined style={{ fontSize: 28, color: "#5a9dad" }} />
      </div>
    );
  }

  return (
    <div style={{
      width: 72, height: 100, borderRadius: 8, flexShrink: 0,
      background: "#f0f2f5", overflow: "hidden",
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <img
        src={src}
        alt="cover"
        onError={() => setError(true)}
        style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }}
      />
    </div>
  );
}

function BookCard({ book, onDelete }) {
  const navigate  = useNavigate();
  const done      = book.progress?.done  ?? 0;
  const total     = book.progress?.total ?? 7;
  const percent   = Math.round((done / total) * 100);
  const stepInfo  = currentStepLabel(book.steps);

  return (
    <Card
      hoverable
      style={{ borderRadius: 12, overflow: "hidden" }}
      styles={{ body: { padding: "16px" } }}
    >
      <div style={{ display: "flex", gap: 14, marginBottom: 14 }}>
        <BookCover slug={book.slug} />
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <Text strong style={{ fontSize: 14, display: "block", lineHeight: 1.4, marginBottom: 4 }}>
            {book.title || book.slug}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {book.author || "Unknown author"}
          </Text>
        </div>
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {Array.from({ length: total }, (_, i) => {
          const s = book.steps?.[String(i + 1)] ?? "pending";
          return (
            <Tooltip key={i} title={STEP_LABELS[i + 1]}>
              <div
                style={{
                  width: 8, height: 8, borderRadius: "50%",
                  background: STATUS_COLOR[s] ?? "#d1d5db",
                  flex: 1,
                }}
              />
            </Tooltip>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <Button
          type="primary"
          icon={<ArrowRightOutlined />}
          style={{ flex: 1 }}
          onClick={() => navigate(`/books/${book.slug}`)}
        >
          Open
        </Button>
        <Popconfirm
          title="Delete this book?"
          description="All files will be removed."
          onConfirm={() => onDelete(book.slug)}
          okText="Delete"
          okButtonProps={{ danger: true }}
          cancelText="Cancel"
        >
          <Button icon={<DeleteOutlined />} danger />
        </Popconfirm>
      </div>
    </Card>
  );
}

function UploadModal({ open, onClose, onUploaded }) {
  const [uploading, setUploading] = useState(false);

  const handleUpload = async ({ file }) => {
    setUploading(true);
    try {
      await uploadBook(file);
      message.success(`"${file.name}" uploaded successfully`);
      onUploaded();
      onClose();
    } catch (e) {
      const detail = e.response?.data?.detail;
      message.error(detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Modal title="Upload a book" open={open} onCancel={onClose} footer={null} width={480}>
      <Dragger
        accept=".epub"
        customRequest={handleUpload}
        showUploadList={false}
        disabled={uploading}
        style={{ padding: "12px 0" }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined style={{ color: "#5a9dad" }} />
        </p>
        <p className="ant-upload-text">Click or drag EPUB file here</p>
        <p className="ant-upload-hint" style={{ color: "#9ca3af" }}>Only .epub format is supported</p>
      </Dragger>
      {uploading && (
        <div style={{ textAlign: "center", marginTop: 16 }}>
          <Spin /> <Text style={{ marginLeft: 8 }}>Parsing book...</Text>
        </div>
      )}
    </Modal>
  );
}

function GutenbergModal({ open, onClose, onImported }) {
  const [query,     setQuery]     = useState("");
  const [results,   setResults]   = useState([]);
  const [searching, setSearching] = useState(false);
  const [importing, setImporting] = useState(null); // gutenberg_id being imported

  const handleSearch = async (value) => {
    if (!value.trim()) return;
    setSearching(true);
    setResults([]);
    try {
      const r = await searchGutenberg(value);
      setResults(r.data.results);
      if (r.data.results.length === 0) message.info("No books found");
    } catch {
      message.error("Search failed");
    } finally {
      setSearching(false);
    }
  };

  const handleImport = async (book) => {
    setImporting(book.id);
    try {
      const r = await importGutenberg({
        gutenberg_id: book.id,
        title:        book.title,
        author:       book.author,
        epub_url:     book.epub_url,
      });
      message.success(`"${r.data.title}" imported (${r.data.chapters} chapters)`);
      onImported();
      onClose();
    } catch (e) {
      const detail = e.response?.data?.detail;
      message.error(detail || "Import failed");
    } finally {
      setImporting(null);
    }
  };

  const handleClose = () => {
    setQuery("");
    setResults([]);
    onClose();
  };

  return (
    <Modal
      title={
        <span>
          <SearchOutlined style={{ marginRight: 8, color: "#5a9dad" }} />
          Search Project Gutenberg
        </span>
      }
      open={open}
      onCancel={handleClose}
      footer={null}
      width={600}
    >
      <Text type="secondary" style={{ display: "block", marginBottom: 16, fontSize: 13 }}>
        Free public domain books.
      </Text>

      <Search
        value={query}
        onChange={e => setQuery(e.target.value)}
        onSearch={handleSearch}
        enterButton="Search"
        size="large"
        loading={searching}
        style={{ marginBottom: 16 }}
      />

      {searching && (
        <div style={{ textAlign: "center", padding: 32 }}>
          <Spin size="large" />
        </div>
      )}

      {results.length > 0 && (
        <List
          dataSource={results}
          style={{ maxHeight: 420, overflowY: "auto" }}
          renderItem={(book) => (
            <List.Item
              style={{ padding: "12px 4px" }}
              actions={[
                <Button
                  key="import"
                  type="primary"
                  icon={<DownloadOutlined />}
                  loading={importing === book.id}
                  disabled={importing !== null && importing !== book.id}
                  onClick={() => handleImport(book)}
                >
                  Import
                </Button>
              ]}
            >
              <List.Item.Meta
                avatar={
                  <Avatar
                    style={{ background: "#e8f4f7", color: "#5a9dad" }}
                    icon={<BookOutlined />}
                  />
                }
                title={
                  <Text strong style={{ fontSize: 14 }}>{book.title}</Text>
                }
                description={
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {book.author}
                    </Text>
                    {book.languages?.length > 0 && (
                      <Tag style={{ marginLeft: 8, fontSize: 11 }}>
                        {book.languages[0]}
                      </Tag>
                    )}
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Modal>
  );
}

export default function BooksPage() {
  const [books,          setBooks]          = useState([]);
  const [loading,        setLoading]        = useState(true);
  const [uploadModal,    setUploadModal]    = useState(false);
  const [gutenbergModal, setGutenbergModal] = useState(false);

  const load = () => {
    setLoading(true);
    getBooks()
      .then(r => setBooks(r.data.books))
      .catch(() => message.error("Failed to load books"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleDelete = async (slug) => {
    try {
      await deleteBook(slug);
      message.success("Book deleted");
      load();
    } catch {
      message.error("Failed to delete");
    }
  };

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "36px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>My Library</Title>
          <Text type="secondary">{books.length} book{books.length !== 1 ? "s" : ""}</Text>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <Button
            icon={<SearchOutlined />}
            size="large"
            onClick={() => setGutenbergModal(true)}
          >
            Search
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            size="large"
            onClick={() => setUploadModal(true)}
          >
            Upload book
          </Button>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", paddingTop: 80 }}>
          <Spin size="large" />
        </div>
      ) : books.length === 0 ? (
        <Empty
          image={<BookOutlined style={{ fontSize: 64, color: "#d1d5db" }} />}
          imageStyle={{ height: 80 }}
          description={
            <span style={{ color: "#9ca3af" }}>
              No books yet. Upload an EPUB or search Project Gutenberg.
            </span>
          }
        >
          <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
            <Button icon={<SearchOutlined />} onClick={() => setGutenbergModal(true)}>
              Search
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadModal(true)}>
              Upload book
            </Button>
          </div>
        </Empty>
      ) : (
        <Row gutter={[20, 20]}>
          {books.map(book => (
            <Col key={book.slug} xs={24} sm={12} md={8} lg={6}>
              <BookCard book={book} onDelete={handleDelete} />
            </Col>
          ))}
        </Row>
      )}

      <UploadModal
        open={uploadModal}
        onClose={() => setUploadModal(false)}
        onUploaded={load}
      />

      <GutenbergModal
        open={gutenbergModal}
        onClose={() => setGutenbergModal(false)}
        onImported={load}
      />
    </div>
  );
}