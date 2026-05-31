import type { ReactNode } from "react";

interface CardProps {
  readonly title?: string;
  readonly icon?: ReactNode;
  readonly meta?: ReactNode;
  readonly children: ReactNode;
  readonly className?: string;
  readonly style?: React.CSSProperties;
}

function Card({ title, icon, meta, children, className = "", style }: CardProps) {
  const hasHeader = title || meta || icon;
  return (
    <div
      className={`rounded-4 border border-hairline bg-surface p-5 shadow-1 ${className}`}
      style={style}
    >
      {hasHeader && (
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {icon}
            {title && (
              <h3 className="text-sm font-semibold text-ink">{title}</h3>
            )}
          </div>
          {meta}
        </div>
      )}
      {children}
    </div>
  );
}

export default Card;
