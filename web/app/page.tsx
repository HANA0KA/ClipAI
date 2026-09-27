import { NewProject } from "@/components/clipai/new-project";
import { ProjectList } from "@/components/clipai/project-list";
import { TikTokNotice } from "@/components/clipai/tiktok-notice";

export default function Home() {
  return (
    <div className="pt-8">
      <TikTokNotice />
      <NewProject />
      <ProjectList />
    </div>
  );
}
