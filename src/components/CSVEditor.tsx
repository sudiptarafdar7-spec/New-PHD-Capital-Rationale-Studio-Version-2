import React, { useState } from 'react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Card } from './ui/card';
import { ScrollArea } from './ui/scroll-area';
import { Trash2, Save } from 'lucide-react';

interface CSVEditorProps {
  initialData: string[][];
  onSave: (data: string[][]) => void;
  onDelete: () => void;
  onContinue: () => void;
}

export default function CSVEditor({ initialData, onSave, onDelete, onContinue }: CSVEditorProps) {
  const [data, setData] = useState<string[][]>(initialData);
  const [hasChanges, setHasChanges] = useState(false);

  const handleCellChange = (rowIndex: number, colIndex: number, value: string) => {
    const newData = [...data];
    newData[rowIndex][colIndex] = value;
    setData(newData);
    setHasChanges(true);
  };

  const handleContinue = () => {
    if (hasChanges) {
      onSave(data);
    }
    onContinue();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg text-foreground">stocks_with_chart.csv</h3>
          <p className="text-sm text-muted-foreground">
            Edit the stock data before generating the PDF report
          </p>
        </div>
        {hasChanges && (
          <span className="text-xs bg-yellow-500/20 text-yellow-600 px-3 py-1 rounded-full">
            Unsaved changes
          </span>
        )}
      </div>

      {/* CSV Table */}
      <Card className="bg-card border-border overflow-hidden">
        <div className="overflow-x-auto overflow-y-auto max-h-[500px]">
          <table className="w-full border-collapse min-w-max">
            <thead className="sticky top-0 z-10">
              <tr className="bg-muted border-b border-border">
                {data[0]?.map((header, index) => (
                  <th
                    key={index}
                    className="px-4 py-3 text-left text-sm text-foreground border-r border-border last:border-r-0 whitespace-nowrap bg-muted"
                  >
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.slice(1).map((row, rowIndex) => (
                <tr
                  key={rowIndex}
                  className="border-b border-border hover:bg-muted/50 transition-colors"
                >
                  {row.map((cell, colIndex) => (
                    <td
                      key={colIndex}
                      className="px-2 py-2 border-r border-border last:border-r-0"
                    >
                      <Input
                        value={cell}
                        onChange={(e) => handleCellChange(rowIndex + 1, colIndex, e.target.value)}
                        className="min-w-[150px] bg-background border-input text-foreground text-sm h-9"
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Action Buttons */}
      <div className="flex gap-3 pt-4">
        <Button
          onClick={handleContinue}
          className="bg-green-600 hover:bg-green-700 text-white flex-1"
        >
          <Save className="w-4 h-4 mr-2" />
          {hasChanges ? 'Save & Continue to PDF Generation' : 'Continue to PDF Generation'}
        </Button>
        <Button
          onClick={onDelete}
          variant="outline"
          className="border-red-500/50 text-red-500 hover:bg-red-600 hover:text-white hover:border-red-600"
        >
          <Trash2 className="w-4 h-4 mr-2" />
          Delete Job
        </Button>
      </div>
    </div>
  );
}
