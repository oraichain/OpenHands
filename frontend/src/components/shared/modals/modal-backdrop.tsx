import React from "react";

interface ModalBackdropProps {
  children: React.ReactNode;
  onClose?: () => void;
}

export function ModalBackdrop({ children, onClose }: ModalBackdropProps) {
  React.useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose?.();
    };

    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, []);

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose?.(); // only close if the click was on the backdrop
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center z-[51]">
      <div
        onClick={handleClick}
        className="fixed inset-0 bg-black/40  backdrop-blur-[12px]"
      />
      <div className="relative">{children}</div>
    </div>
  );
}
