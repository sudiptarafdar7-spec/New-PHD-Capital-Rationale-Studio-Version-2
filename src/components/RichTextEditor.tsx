import React, { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { Button } from './ui/button';
import { Textarea } from './ui/textarea';
import { 
  Bold, 
  Italic, 
  Underline, 
  List, 
  ListOrdered, 
  AlignLeft, 
  AlignCenter, 
  AlignRight,
  Code
} from 'lucide-react';

interface RichTextEditorProps {
  value: string;
  onChange: (value: string) => void;
  id?: string;
  label?: string;
}

export function RichTextEditor({ value, onChange, id, label }: RichTextEditorProps) {
  const [activeTab, setActiveTab] = useState<'visual' | 'html'>('visual');
  const [htmlContent, setHtmlContent] = useState(value);

  const applyFormat = (format: string, value?: string) => {
    document.execCommand(format, false, value);
  };

  const handleVisualChange = (e: React.FormEvent<HTMLDivElement>) => {
    const content = e.currentTarget.innerHTML;
    setHtmlContent(content);
    onChange(content);
  };

  const handleHtmlChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const content = e.target.value;
    setHtmlContent(content);
    onChange(content);
  };

  return (
    <div className="space-y-2">
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'visual' | 'html')}>
        <div className="flex items-center justify-between mb-2">
          <TabsList className="bg-muted border border-border">
            <TabsTrigger value="visual" className="text-muted-foreground data-[state=active]:bg-background data-[state=active]:text-foreground">
              Visual Editor
            </TabsTrigger>
            <TabsTrigger value="html" className="text-muted-foreground data-[state=active]:bg-background data-[state=active]:text-foreground">
              HTML Source
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="visual" className="mt-0">
          {/* Toolbar */}
          <div className="flex flex-wrap gap-1 p-2 bg-muted border border-border border-b-0 rounded-t-lg">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => applyFormat('bold')}
              className="h-8 w-8 p-0 text-foreground hover:bg-accent"
              title="Bold"
            >
              <Bold className="w-4 h-4" />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => applyFormat('italic')}
              className="h-8 w-8 p-0 text-foreground hover:bg-accent"
              title="Italic"
            >
              <Italic className="w-4 h-4" />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => applyFormat('underline')}
              className="h-8 w-8 p-0 text-foreground hover:bg-accent"
              title="Underline"
            >
              <Underline className="w-4 h-4" />
            </Button>
            <div className="w-px h-8 bg-border mx-1" />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => applyFormat('insertUnorderedList')}
              className="h-8 w-8 p-0 text-foreground hover:bg-accent"
              title="Bullet List"
            >
              <List className="w-4 h-4" />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => applyFormat('insertOrderedList')}
              className="h-8 w-8 p-0 text-foreground hover:bg-accent"
              title="Numbered List"
            >
              <ListOrdered className="w-4 h-4" />
            </Button>
            <div className="w-px h-8 bg-border mx-1" />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => applyFormat('justifyLeft')}
              className="h-8 w-8 p-0 text-foreground hover:bg-accent"
              title="Align Left"
            >
              <AlignLeft className="w-4 h-4" />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => applyFormat('justifyCenter')}
              className="h-8 w-8 p-0 text-foreground hover:bg-accent"
              title="Align Center"
            >
              <AlignCenter className="w-4 h-4" />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => applyFormat('justifyRight')}
              className="h-8 w-8 p-0 text-foreground hover:bg-accent"
              title="Align Right"
            >
              <AlignRight className="w-4 h-4" />
            </Button>
          </div>

          {/* Editable Area */}
          <div
            id={id}
            contentEditable
            onInput={handleVisualChange}
            dangerouslySetInnerHTML={{ __html: htmlContent }}
            className="min-h-[200px] p-4 bg-background border border-border rounded-b-lg text-foreground focus:outline-none focus:ring-2 focus:ring-ring overflow-auto"
            style={{ maxHeight: '400px' }}
          />
        </TabsContent>

        <TabsContent value="html" className="mt-0">
          <Textarea
            value={htmlContent}
            onChange={handleHtmlChange}
            className="min-h-[250px] font-mono text-sm bg-background border-input text-foreground"
            placeholder="Enter HTML content..."
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
