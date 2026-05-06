import React, { useState, useEffect } from 'react';
import { FileCode, Save, Loader2 } from 'lucide-react';
import { API_ENDPOINTS, getAuthHeaders } from '../lib/api-config';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { toast } from 'sonner';

export default function PdfTemplatePage() {
  const [loading, setLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [formData, setFormData] = useState({
    company_name: '',
    registration_details: '',
    disclaimer_text: '',
    disclosure_text: '',
    company_data: '',
  });
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  useEffect(() => {
    loadTemplate();
  }, []);

  const loadTemplate = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(API_ENDPOINTS.pdfTemplate.get, {
        headers: getAuthHeaders(token || ''),
      });

      if (response.ok) {
        const data = await response.json();
        setFormData({
          company_name: data.company_name || '',
          registration_details: data.registration_details || '',
          disclaimer_text: data.disclaimer_text || '',
          disclosure_text: data.disclosure_text || '',
          company_data: data.company_data || '',
        });
        if (data.updated_at) {
          setLastUpdated(data.updated_at);
        }
      } else {
        const error = await response.json();
        toast.error(error.error || 'Failed to load PDF template');
      }
    } catch (error) {
      console.error('Error loading PDF template:', error);
      toast.error('Error loading PDF template');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(API_ENDPOINTS.pdfTemplate.update, {
        method: 'PUT',
        headers: getAuthHeaders(token || ''),
        body: JSON.stringify(formData),
      });

      if (response.ok) {
        const data = await response.json();
        if (data.updated_at) {
          setLastUpdated(data.updated_at);
        }
        toast.success('PDF template updated', {
          description: 'The changes will be applied to all future generated reports.',
        });
      } else {
        const error = await response.json();
        toast.error(error.error || 'Failed to save PDF template');
      }
    } catch (error) {
      console.error('Error saving PDF template:', error);
      toast.error('Error saving PDF template');
    } finally {
      setIsSaving(false);
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return new Intl.DateTimeFormat('en-IN', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  };

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl text-foreground mb-1">PDF Template</h1>
        <p className="text-muted-foreground">Configure letterhead information and legal disclaimers for PDF reports</p>
        {lastUpdated && (
          <p className="text-xs text-muted-foreground mt-2">
            Last updated: {formatDate(lastUpdated)}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Company Name */}
        <Card className="bg-card border-border shadow-sm p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 bg-blue-500/20 rounded-xl">
              <FileCode className="w-6 h-6 text-blue-500" />
            </div>
            <div>
              <h2 className="text-lg text-foreground">Company Name</h2>
              <p className="text-sm text-muted-foreground">Your company name for letterhead</p>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="company-name" className="text-foreground">
              Company Name
            </Label>
            <Input
              id="company-name"
              value={formData.company_name}
              onChange={(e) => setFormData({ ...formData, company_name: e.target.value })}
              className="bg-background border-input text-foreground"
              placeholder="Enter company name"
            />
          </div>
        </Card>

        {/* Registration Details */}
        <Card className="bg-card border-border shadow-sm p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 bg-purple-500/20 rounded-xl">
              <FileCode className="w-6 h-6 text-purple-500" />
            </div>
            <div>
              <h2 className="text-lg text-foreground">Registration Details</h2>
              <p className="text-sm text-muted-foreground">All registration numbers in one line</p>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="registration-details" className="text-foreground">
              Registration Details
            </Label>
            <Input
              id="registration-details"
              value={formData.registration_details}
              onChange={(e) => setFormData({ ...formData, registration_details: e.target.value })}
              className="bg-background border-input text-foreground"
              placeholder="SEBI Regd No - XXX AMFI Regd No - XXX..."
            />
            <p className="text-xs text-muted-foreground">
              Enter all registration numbers separated by spaces (SEBI, AMFI, APMI, BSE, CIN, etc.)
            </p>
          </div>
        </Card>

        {/* Disclaimer */}
        <Card className="bg-card border-border shadow-sm p-6 lg:col-span-2">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 bg-green-500/20 rounded-xl">
              <FileCode className="w-6 h-6 text-green-500" />
            </div>
            <div>
              <h2 className="text-lg text-foreground">Disclaimer</h2>
              <p className="text-sm text-muted-foreground">Legal disclaimer text for PDF reports</p>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="disclaimer" className="text-foreground">
              Disclaimer Text
            </Label>
            <Textarea
              id="disclaimer"
              value={formData.disclaimer_text}
              onChange={(e) => setFormData({ ...formData, disclaimer_text: e.target.value })}
              className="bg-background border-input text-foreground min-h-[120px]"
              placeholder="This is a computer-generated document and does not require a signature..."
            />
          </div>
        </Card>

        {/* Disclosure */}
        <Card className="bg-card border-border shadow-sm p-6 lg:col-span-2">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 bg-orange-500/20 rounded-xl">
              <FileCode className="w-6 h-6 text-orange-500" />
            </div>
            <div>
              <h2 className="text-lg text-foreground">Disclosure</h2>
              <p className="text-sm text-muted-foreground">Disclosure statement for regulatory compliance</p>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="disclosure" className="text-foreground">
              Disclosure Statement
            </Label>
            <Textarea
              id="disclosure"
              value={formData.disclosure_text}
              onChange={(e) => setFormData({ ...formData, disclosure_text: e.target.value })}
              className="bg-background border-input text-foreground min-h-[120px]"
              placeholder="We and our affiliates, officers, directors, and employees may have positions in the securities mentioned..."
            />
          </div>
        </Card>

        {/* Company Data */}
        <Card className="bg-card border-border shadow-sm p-6 lg:col-span-2">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 bg-cyan-500/20 rounded-xl">
              <FileCode className="w-6 h-6 text-cyan-500" />
            </div>
            <div>
              <h2 className="text-lg text-foreground">Company Data</h2>
              <p className="text-sm text-muted-foreground">Additional company information and data</p>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="company-data" className="text-foreground">
              Company Data
            </Label>
            <Textarea
              id="company-data"
              value={formData.company_data}
              onChange={(e) => setFormData({ ...formData, company_data: e.target.value })}
              className="bg-background border-input text-foreground min-h-[120px]"
              placeholder="Enter company data and additional information here..."
            />
          </div>
        </Card>
      </div>

      {/* Save Button */}
      <div className="flex justify-end">
        <Button
          onClick={handleSave}
          data-tour="pdf-save"
          disabled={isSaving}
          className="gradient-primary glow-primary h-11 w-full sm:w-auto"
        >
          {isSaving ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Saving...
            </>
          ) : (
            <>
              <Save className="w-4 h-4 mr-2" />
              Save Template Settings
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
