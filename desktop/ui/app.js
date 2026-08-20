import { invoke } from "https://esm.tauri.app/v2/core";
import { listen } from "https://esm.tauri.app/v2/event";

const $ = (selector) => document.querySelector(selector);
const timeline = $("#timeline");
let connected = false;
let generating = false;
let stream = null;

function setStatus(text, active = connected) { $("#status").textContent = text; $("#status").classList.toggle("active", active); }
function lockControls() {
  $("#prompt").disabled = !connected || generating;
  $("#send").disabled = !connected || generating;
  $("#stop").disabled = !generating;
  for (const id of ["#new-session", "#resume", "#checkpoint", "#handoff", "#show-all-diff"]) $(id).disabled = !connected || generating;
}
function addItem(item) {
  timeline.querySelector(".empty")?.remove();
  const article = document.createElement("article");
  article.className = item.type;
  if (item.type === "tool_call") article.textContent = `调用工具：${item.name}`;
  else if (item.type === "tool_result") article.textContent = `${item.success ? "完成" : "失败"}：${item.name}\n${item.output}`;
  else article.textContent = item.text || "";
  timeline.append(article); timeline.scrollTop = timeline.scrollHeight;
  return article;
}
function renderTimeline(items) { timeline.replaceChildren(); items.forEach(addItem); }
function renderSessions(sessions, selected) {
  const nav = $("#sessions"); nav.replaceChildren();
  for (const session of sessions) { const button = document.createElement("button"); button.className = session.id === selected ? "session selected" : "session"; button.textContent = session.title || "新对话"; button.title = session.updated_at || ""; button.onclick = () => request({ action: "select_session", session_id: session.id }); nav.append(button); }
}
function renderTask(task) {
  const details = $("#task-details"); details.replaceChildren();
  const rows = [["状态", task?.status || "空闲"], ["目标", task?.goal || "暂无"], ["下一步", (task?.next_steps || []).join("；") || "无"], ["检查点", String(task?.checkpoint_count || 0)]];
  for (const [key, value] of rows) { const dt = document.createElement("dt"), dd = document.createElement("dd"); dt.textContent = key; dd.textContent = value; details.append(dt, dd); }
  $("#task-goal").textContent = task?.goal || "暂无活动任务";
  const files = $("#changed-files"); files.replaceChildren();
  for (const path of task?.changed_files || []) { const button = document.createElement("button"); button.className = "file"; button.textContent = path; button.onclick = () => backend({ action: "task_action", name: "diff", path }); files.append(button); }
  if (!task?.changed_files?.length) files.innerHTML = '<p class="muted">尚无记录</p>';
}
async function request(payload) { return invoke("send_backend", { payload }); }

await listen("backend-event", ({ payload }) => {
  switch (payload.type) {
    case "ready": setStatus("后端就绪，正在初始化…"); break;
    case "started": connected = true; $("#workdir").value = payload.workdir; $("#project-name").textContent = "新对话"; $("#auto-approve").disabled = true; setStatus("已就绪", true); renderSessions(payload.sessions || [], null); lockControls(); break;
    case "session": renderSessions(payload.sessions || [], payload.session_id); renderTimeline(payload.timeline || []); break;
    case "timeline": addItem(payload.item); break;
    case "token": if (!stream) stream = addItem({ type: "assistant", text: "" }); stream.textContent += payload.text; timeline.scrollTop = timeline.scrollHeight; break;
    case "complete": if (!stream) addItem({ type: "assistant", text: payload.text }); stream = null; generating = false; setStatus("已完成（正常退出）", true); lockControls(); break;
    case "cancelled": stream = null; generating = false; addItem({ type: "cancelled", text: payload.message || "生成退出：已停止" }); setStatus(payload.exit_kind === "external_cancel" ? "异常退出：外层取消" : "已停止：本地取消", true); lockControls(); break;
    case "task_state": renderTask(payload.task); break;
    case "diff": $("#diff").hidden = false; $("#diff").textContent = payload.content; break;
    case "error": addItem({ type: "error", text: payload.message }); generating = false; stream = null; setStatus("异常退出：请求或本地处理失败", connected); lockControls(); break;
  }
});

$("#pick-project").onclick = async () => { const path = await invoke("choose_project"); if (path) { $("#workdir").value = path; if (connected) await invoke("switch_project", { workdir: path }); } };
$("#connect").onclick = async () => {
  const workdir = $("#workdir").value.trim(); if (!workdir || !connected) return;
  try { await invoke("switch_project", { workdir }); }
  catch (error) { addItem({ type: "error", text: String(error) }); setStatus("切换失败", true); }
};
$("#new-session").onclick = () => request({ action: "new_session" });
$("#resume").onclick = () => request({ action: "task_action", name: "resume" });
$("#checkpoint").onclick = () => request({ action: "task_action", name: "checkpoint" });
$("#handoff").onclick = () => request({ action: "task_action", name: "handoff" });
$("#show-all-diff").onclick = () => request({ action: "task_action", name: "diff" });
$("#stop").onclick = () => request({ action: "cancel" });
$("#composer").onsubmit = async (event) => { event.preventDefault(); const text = $("#prompt").value.trim(); if (!text || !connected || generating) return; generating = true; lockControls(); $("#prompt").value = ""; setStatus("生成中…", true); await request({ action: "message", text }); };
$("#prompt").onkeydown = (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("#composer").requestSubmit(); } };
