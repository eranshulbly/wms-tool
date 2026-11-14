import api from './api';

// Beat Outstanding API (/api/beat-outstanding/*) — the server always acts on the Cadila
// company, so no call carries a company. Admin and manager-type roles.
//
// The Tally outstanding report is never stored on the server: the page keeps the picked
// file and sends it (form field `outstanding`) with every call that shows or downloads
// amounts.

const withOutstanding = (outstanding, fields = {}) => {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => fd.append(k, v ?? ''));
  if (outstanding) fd.append('outstanding', outstanding);
  return fd;
};
const MULTIPART = { headers: { 'Content-Type': 'multipart/form-data' } };

const data = (p) => p.then((res) => res.data);

// Today's beat plan; with the Tally report, its amounts too.
export const getBeatReport = (outstanding) =>
  outstanding
    ? data(api.post('beat-outstanding/report', withOutstanding(outstanding), MULTIPART))
    : data(api.get('beat-outstanding/report'));

// Downloads come back as a Blob; the server names the file.
const download = (path, params, fallback, outstanding, fields) =>
  api.post(path, withOutstanding(outstanding, fields), { ...MULTIPART, params, responseType: 'blob' }).then((res) => {
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

export const downloadExecutive = (date, exec, outstanding) =>
  download('beat-outstanding/export', { date }, 'outstanding.xlsx', outstanding, {
    user_id: exec.user_id,
    se_name: exec.se_name,
  });

export const downloadAll = (date, outstanding) =>
  download('beat-outstanding/export-all', { date }, 'beat_outstanding.zip', outstanding);

export const getExecBeats = () => data(api.get('beat-outstanding/exec-beats'));

// Replaces the whole executive → beats table.
export const saveExecBeats = (rows) => data(api.put('beat-outstanding/exec-beats', { rows }));

// Reads a User / Beat file into rows for the table — nothing is saved until saveExecBeats.
export const parseExecBeatsFile = (file) => {
  const fd = new FormData();
  fd.append('file', file);
  return data(api.post('beat-outstanding/exec-beats/parse', fd, { headers: { 'Content-Type': 'multipart/form-data' } }));
};

export const downloadUnassigned = (outstanding) =>
  download('beat-outstanding/export-unassigned', {}, 'unassigned_dealers.xlsx', outstanding);

// Sets by hand the beats an executive covers today (no beat plan file needed).
export const setDayBeats = (seName, beats) => data(api.put('beat-outstanding/day-beats', { se_name: seName, beats }));

// A failed download comes back as a Blob; its JSON error message, if any.
export const readBlobError = async (error) => {
  const data = error?.response?.data;
  if (data instanceof Blob) {
    try {
      return JSON.parse(await data.text())?.msg || null;
    } catch (e) {
      return null;
    }
  }
  return data?.msg || null;
};
