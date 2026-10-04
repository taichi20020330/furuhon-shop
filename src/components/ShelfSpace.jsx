import { useEffect, useRef } from "react";
import { SPACE_HTML, mountShelfSpace } from "../space/shelfSpace.js";

// 空間エンジン（命令型）を React の部品として包む。本棚が変わるたびに作り直す。
export default function ShelfSpace({ shelf, intro }) {
  const ref = useRef(null);
  useEffect(() => {
    const root = ref.current;
    root.innerHTML = SPACE_HTML;
    const h = mountShelfSpace(root, { books: shelf.books, shopName: `${shelf.name}の本棚`, orderEndpoint: shelf.orderEndpoint || "", intro });
    return () => { h.destroy(); root.innerHTML = ""; };
  }, [shelf, intro]);
  return <div ref={ref} className="space-root" />;
}
