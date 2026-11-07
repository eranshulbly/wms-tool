import api from './api';

// Beat Outstanding API (/api/beat-outstanding/*) — Ebco only: the server always acts on
// the Ebco company, so no call carries a company. Admin only.

const data = (p) => p.then((res) => res.data);

export const getBeatFeedStatus = () => data(api.get('beat-outstanding/status'));

export const getBeatReport = (date) => data(api.get('beat-outstanding/report', { params: date ? { date } : {} }));

export const uploadBeatFeed = (feed, file) => {
  const fd = new FormData();
  fd.append('feed', feed);
  fd.append('file', file);
  return data(api.post('beat-outstanding/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } }));
};

// Downloads come back as a Blob; the server names the file.
const download = (path, params, fallback) =>
  api.get(path, { params, responseType: 'blob' }).then((res) => {
    const disposition = res.headers['content-disposition'] || '';
    const match = /filename[^;=\n]*=(?:"?)([^";\n]*)/.exec(disposition);
    const url = URL.createObjectURL(res.data);
    const a = document.createElement('a');
    a.href = url;
    a.download = match ? match[1].trim() : fallback;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });

export const downloadExecutive = (date, exec) =>
  download('beat-outstanding/export', { date, user_id: exec.user_id, se_name: exec.se_name }, 'outstanding.xlsx');

export const downloadAll = (date) => download('beat-outstanding/export-all', { date }, 'beat_outstanding.zip');

export const getExecBeats = () => data(api.get('beat-outstanding/exec-beats'));

// Replaces the whole executive → beats table.
export const saveExecBeats = (rows) => data(api.put('beat-outstanding/exec-beats', { rows }));

// Reads a User / Beat file into rows for the table — nothing is saved until saveExecBeats.
export const parseExecBeatsFile = (file) => {
  const fd = new FormData();
  fd.append('file', file);
  return data(api.post('beat-outstanding/exec-beats/parse', fd, { headers: { 'Content-Type': 'multipart/form-data' } }));
};
