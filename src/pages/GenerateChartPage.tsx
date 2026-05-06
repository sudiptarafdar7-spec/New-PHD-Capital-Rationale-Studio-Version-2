import React, { useState, useRef } from 'react';
import { BarChart3, Calendar, Clock, Download, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import { StockAutocompleteInput, Stock } from '../components/StockAutocompleteInput';
import { API_ENDPOINTS, getAuthHeaders } from '../lib/api-config';
import { useAuth } from '../lib/auth-context';

interface GenerateChartPageProps {
  onNavigate?: (page: string) => void;
}

interface ChartData {
  chartId: string;
  chartUrl: string;
  downloadUrl: string;
  cmp: number | null;
  cmpDatetime: string | null;
}

export default function GenerateChartPage({ onNavigate }: GenerateChartPageProps) {
  const { token } = useAuth();
  
  const [stockSymbol, setStockSymbol] = useState('');
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null);
  const [chartType, setChartType] = useState<string>('Daily');
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [time, setTime] = useState('15:30');
  
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [chartImageUrl, setChartImageUrl] = useState<string | null>(null);
  
  const chartContainerRef = useRef<HTMLDivElement>(null);

  const handleStockSelect = (stock: Stock | null, symbol: string) => {
    setStockSymbol(symbol);
    setSelectedStock(stock);
  };

  const handleGenerateChart = async () => {
    if (!stockSymbol) {
      toast.error('Please select a stock symbol');
      return;
    }

    if (!selectedStock?.securityId) {
      toast.error('Please select a valid stock from the dropdown');
      return;
    }

    if (!date) {
      toast.error('Please select a date');
      return;
    }

    setIsGenerating(true);
    setChartData(null);
    setChartImageUrl(null);

    try {
      const response = await fetch(API_ENDPOINTS.generateChart.generate, {
        method: 'POST',
        headers: getAuthHeaders(token || ''),
        body: JSON.stringify({
          symbol: stockSymbol,
          security_id: selectedStock.securityId,
          short_name: selectedStock.shortName || stockSymbol,
          exchange: selectedStock.exchange || 'NSE',
          chart_type: chartType,
          date: date,
          time: time || '15:30',
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to generate chart');
      }

      if (data.success) {
        setChartData({
          chartId: data.chart_id,
          chartUrl: data.chart_url,
          downloadUrl: data.download_url,
          cmp: data.cmp,
          cmpDatetime: data.cmp_datetime,
        });

        const imageResponse = await fetch(data.chart_url, {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });

        if (imageResponse.ok) {
          const blob = await imageResponse.blob();
          const imageUrl = URL.createObjectURL(blob);
          setChartImageUrl(imageUrl);
        }

        toast.success('Chart generated successfully!');

        setTimeout(() => {
          chartContainerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
      } else {
        throw new Error(data.error || 'Failed to generate chart');
      }
    } catch (error: any) {
      console.error('Error generating chart:', error);
      toast.error(error.message || 'Failed to generate chart');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownloadChart = async () => {
    if (!chartData?.downloadUrl) return;

    setIsDownloading(true);

    try {
      const response = await fetch(chartData.downloadUrl, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to download chart');
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${stockSymbol}_${chartType}_${date}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      toast.success('Chart downloaded successfully!');

      setChartData(null);
      setChartImageUrl(null);
    } catch (error: any) {
      console.error('Error downloading chart:', error);
      toast.error(error.message || 'Failed to download chart');
    } finally {
      setIsDownloading(false);
    }
  };

  const handleClearChart = () => {
    if (chartImageUrl) {
      URL.revokeObjectURL(chartImageUrl);
    }
    setChartData(null);
    setChartImageUrl(null);
  };

  const handleReset = () => {
    handleClearChart();
    setStockSymbol('');
    setSelectedStock(null);
    setChartType('Daily');
    setDate(new Date().toISOString().split('T')[0]);
    setTime('15:30');
  };

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl text-foreground mb-1 flex items-center gap-2">
            <div className="p-2 bg-teal-500/10 rounded-lg">
              <BarChart3 className="w-6 h-6 text-teal-500" />
            </div>
            Generate Chart
          </h1>
          <p className="text-sm sm:text-base text-muted-foreground">
            Generate professional stock charts with technical indicators
          </p>
        </div>
      </div>

      <Card className="premium-card">
        <div className="p-5 sm:p-6 border-b border-border bg-gradient-to-r from-teal-500/5 to-transparent">
          <h2 className="text-lg text-foreground flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-teal-500" />
            Chart Settings
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Configure the chart parameters and generate
          </p>
        </div>

        <div className="p-5 sm:p-6 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <Label className="text-sm font-medium">
                Stock Symbol <span className="text-red-500">*</span>
              </Label>
              <StockAutocompleteInput
                value={stockSymbol}
                onSelect={handleStockSelect}
                token={token || ''}
                placeholder="Type to search stocks (e.g., RELIANCE, TCS)..."
                disabled={isGenerating}
                useV2Api={true}
              />
              {selectedStock && (
                <p className="text-xs text-muted-foreground">
                  {selectedStock.name} ({selectedStock.exchange}) - Security ID: {selectedStock.securityId}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-medium">
                Chart Type <span className="text-red-500">*</span>
              </Label>
              <Select value={chartType} onValueChange={setChartType} disabled={isGenerating}>
                <SelectTrigger className="bg-background border-input">
                  <SelectValue placeholder="Select chart type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Daily">Daily</SelectItem>
                  <SelectItem value="Weekly">Weekly</SelectItem>
                  <SelectItem value="Monthly">Monthly</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-medium flex items-center gap-2">
                <Calendar className="w-4 h-4 text-muted-foreground" />
                Date <span className="text-red-500">*</span>
              </Label>
              <Input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                disabled={isGenerating}
                className="bg-background border-input"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-medium flex items-center gap-2">
                <Clock className="w-4 h-4 text-muted-foreground" />
                Time
              </Label>
              <Input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                disabled={isGenerating}
                className="bg-background border-input"
              />
              <p className="text-xs text-muted-foreground">
                Default: 3:30 PM (Market Close)
              </p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t border-border">
            <Button
              onClick={handleGenerateChart}
              disabled={isGenerating || !stockSymbol || !selectedStock?.securityId}
              className="gradient-primary flex-1 sm:flex-none"
              data-tour="chart-generate"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Generating Chart...
                </>
              ) : (
                <>
                  <BarChart3 className="w-4 h-4 mr-2" />
                  Generate Chart
                </>
              )}
            </Button>

            <Button
              variant="outline"
              onClick={handleReset}
              disabled={isGenerating}
              className="flex-1 sm:flex-none"
            >
              <RefreshCw className="w-4 h-4 mr-2" />
              Reset
            </Button>
          </div>
        </div>
      </Card>

      {(chartImageUrl || isGenerating) && (
        <Card className="premium-card" ref={chartContainerRef}>
          <div className="p-5 sm:p-6 border-b border-border bg-gradient-to-r from-green-500/5 to-transparent">
            <div className="flex items-center justify-between">
              <h2 className="text-lg text-foreground flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-green-500" />
                Generated Chart
              </h2>
              {chartData && (
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    onClick={handleDownloadChart}
                    disabled={isDownloading}
                    className="bg-green-600 hover:bg-green-700"
                  >
                    {isDownloading ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Downloading...
                      </>
                    ) : (
                      <>
                        <Download className="w-4 h-4 mr-2" />
                        Download Chart
                      </>
                    )}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleClearChart}
                    className="border-red-500/50 text-red-500 hover:bg-red-500 hover:text-white"
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    Clear
                  </Button>
                </div>
              )}
            </div>
            {chartData?.cmp && (
              <p className="text-sm text-muted-foreground mt-1">
                CMP: ₹{chartData.cmp.toFixed(2)}
              </p>
            )}
          </div>

          <div className="p-5 sm:p-6">
            {isGenerating ? (
              <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                <Loader2 className="w-12 h-12 animate-spin text-teal-500 mb-4" />
                <p className="text-lg">Generating chart...</p>
                <p className="text-sm mt-2">This may take a few seconds</p>
              </div>
            ) : chartImageUrl ? (
              <div className="rounded-lg overflow-hidden border border-border">
                <img
                  src={chartImageUrl}
                  alt={`${stockSymbol} ${chartType} Chart`}
                  className="w-full h-auto"
                />
              </div>
            ) : null}
          </div>
        </Card>
      )}

      <Card className="premium-card">
        <div className="p-5 sm:p-6">
          <h3 className="text-sm font-medium text-muted-foreground mb-3">Chart Features</h3>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm text-muted-foreground">
            <li className="flex items-center gap-2">
              <div className="w-2 h-2 bg-blue-500 rounded-full" />
              Candlestick patterns with volume
            </li>
            <li className="flex items-center gap-2">
              <div className="w-2 h-2 bg-green-500 rounded-full" />
              Moving Averages (MA20, MA50, MA100, MA200)
            </li>
            <li className="flex items-center gap-2">
              <div className="w-2 h-2 bg-purple-500 rounded-full" />
              RSI (Relative Strength Index) indicator
            </li>
            <li className="flex items-center gap-2">
              <div className="w-2 h-2 bg-orange-500 rounded-full" />
              Current Market Price (CMP) display
            </li>
          </ul>
          <p className="text-xs text-muted-foreground mt-4 pt-4 border-t border-border">
            Note: Charts are automatically deleted from the server after download or within 24 hours.
          </p>
        </div>
      </Card>
    </div>
  );
}
