import { useEffect, useState } from "react";

export default function useTypingEffect(text = "", speed = 15) {
  const [displayedText, setDisplayedText] = useState("");

  useEffect(() => {
    if (!text) {
      setDisplayedText("");
      return;
    }

    setDisplayedText("");
    let index = 0;

    const interval = setInterval(() => {
      setDisplayedText((prev) => prev + text.charAt(index));
      index++;

      if (index >= text.length) {
        clearInterval(interval);
      }
    }, speed);

    return () => clearInterval(interval);
  }, [text, speed]);

  return displayedText;
}
