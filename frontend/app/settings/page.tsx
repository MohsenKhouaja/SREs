"use client";

import {FormEvent, useEffect, useState} from "react";
import {Save} from "lucide-react";
import {PageHeader} from "@/components/page-header";
import {Button} from "@/components/ui/button";
import {Panel} from "@/components/ui/panel";
import {apiFetch} from "@/lib/api";

type Provider = "deterministic" | "openai" | "gemini" | "groq";

export default function SettingsPage() {
  const [provider, setProvider] = useState<Provider>("deterministic");
  const [apiKey, setApiKey] = useState("");
  const [configured, setConfigured] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => { apiFetch<{llm_provider: Provider; api_key_configured: boolean}>("/settings").then((data) => {setProvider(data.llm_provider); setConfigured(data.api_key_configured);}).catch(() => setMessage("Could not load runtime settings.")); }, []);

  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setMessage("");
    try { const data = await apiFetch<{api_key_configured: boolean}>("/settings", {method: "POST", body: JSON.stringify({llm_provider: provider, api_key: apiKey})}); setConfigured(data.api_key_configured || configured); setApiKey(""); setMessage("Runtime provider updated. Keys are held in backend memory and never returned to the browser."); } catch (caught) { setMessage(caught instanceof Error ? caught.message : "Could not save settings"); } finally { setSaving(false); }
  }

  return <>
    <PageHeader title="Settings" description="Choose deterministic analysis or enrich correlation with an LLM provider. Environment variables remain the recommended configuration path." />
    <Panel className="form-panel"><form onSubmit={save}><div className="field"><label htmlFor="provider">Analysis provider</label><select className="select" id="provider" value={provider} onChange={(event) => setProvider(event.target.value as Provider)}><option value="deterministic">Deterministic (no key required)</option><option value="openai">OpenAI</option><option value="gemini">Gemini</option><option value="groq">Groq</option></select><small>Deterministic mode keeps simulations reproducible and fully functional.</small></div>{provider !== "deterministic" && <div className="field"><label htmlFor="api-key">API key</label><input className="input" id="api-key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={configured ? "Key configured — enter to replace" : "Enter provider API key"} /><small>The UI never retrieves an existing secret. Restarting the backend clears keys entered here.</small></div>}<Button variant="primary" type="submit" disabled={saving}><Save size={16} aria-hidden="true" />{saving ? "Saving…" : "Save runtime settings"}</Button>{message && <p className="subtle" role="status" style={{marginTop: 14, marginBottom: 0}}>{message}</p>}</form></Panel>
  </>;
}
