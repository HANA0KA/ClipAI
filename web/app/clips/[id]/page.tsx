import { ClipEditor } from "@/components/clipai/clip-editor";

export default async function ClipPage({ params }: PageProps<"/clips/[id]">) {
  const { id } = await params;
  return <ClipEditor id={id} />;
}
