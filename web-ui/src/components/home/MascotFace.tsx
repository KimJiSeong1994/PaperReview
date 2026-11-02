interface MascotFaceProps {
  /** Rendered size in CSS pixels; the 2x asset covers dense screens. */
  size: number;
  className?: string;
}

/**
 * The hero llama's face close-up (with the RESEARCH headband), used as the
 * assistant's avatar. Decorative: the name "집현전" sits next to it.
 */
function MascotFace({ size, className }: MascotFaceProps) {
  return (
    <picture className={`mascot-face${className ? ` ${className}` : ''}`}>
      <source type="image/webp" srcSet="/jiphyeonjeon-face.webp 1x, /jiphyeonjeon-face@2x.webp 2x" />
      <img
        src="/jiphyeonjeon-face.png"
        srcSet="/jiphyeonjeon-face.png 1x, /jiphyeonjeon-face@2x.png 2x"
        alt=""
        width={size}
        height={size}
      />
    </picture>
  );
}

export default MascotFace;
