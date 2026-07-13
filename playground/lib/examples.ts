export type Example = { label: string; want: string[]; where: string | null };

export const EXAMPLES: Example[] = [
  { label: "Just the basics",
    want: ["book name", "writer"], where: null },
  { label: "Same data, different words",
    want: ["headline", "penned by"], where: null },
  { label: "Sci-fi under $25",
    want: ["book name", "cost", "genre"],
    where: "science fiction cheaper than 25 dollars" },
  { label: "Too vague (watch it refuse)",
    want: ["book name"], where: "only the good ones" },
  { label: "Written in French",
    want: ["book name", "tongue"], where: "written in French" },
  { label: "Young authors",
    want: ["book name", "author", "author's birth year"],
    where: "author born after 1980" },
  { label: "中文也通 (Mandarin filter)",
    want: ["book name", "writer", "cost", "author_birth_year"],
    where: "價格低於 $20, 作者 35 歲以上" },
];
