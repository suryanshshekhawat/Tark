import { renderLatexText } from "../latex/latexRender";

export function LatexPreview({
  latex,
  onEdit,
  onConfirm,
}: {
  latex: string;
  onEdit: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="preview-stage">
      <div className="paper">
        <div className="paper-text">{renderLatexText(latex, "preview")}</div>
      </div>
      <div className="preview-actions">
        <button className="secondary" onClick={onEdit}>
          Edit
        </button>
        <button onClick={onConfirm}>Looks right — Verify</button>
      </div>
    </div>
  );
}
